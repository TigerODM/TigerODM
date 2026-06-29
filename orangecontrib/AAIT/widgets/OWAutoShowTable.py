from orangecanvas.localization import Translator  # pylint: disable=wrong-import-order
_tr = Translator("Orange", "biolab.si", "Orange")
del Translator
import concurrent.futures
from dataclasses import dataclass
from typing import (
    Optional, Union, Sequence, List, TypedDict, Tuple, Any, Container
)

import numpy as np
from scipy.sparse import issparse

from AnyQt.QtWidgets import (
    QTableView, QHeaderView, QApplication, QStyle, QStyleOptionHeader,
    QStyleOptionViewItem
)
from AnyQt.QtGui import QColor, QClipboard, QPainter
from AnyQt.QtCore import (
    QTimer, Qt, QSize, QMetaObject, QItemSelectionModel, QModelIndex, QRect,
    QAbstractProxyModel, QObject, QEvent
)
from AnyQt.QtCore import Slot

from orangewidget.gui import OrangeUserRole

import Orange.data
from Orange.data.table import Table
from Orange.data.sql.table import SqlTable

from Orange.widgets import gui
from Orange.widgets.data.utils.models import RichTableModel, TableSliceProxy
from Orange.widgets.utils.itemdelegates import TableDataDelegate
from Orange.widgets.utils.tableview import table_selection_to_mime_data
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import OWWidget, Input, Output, Msg
from Orange.widgets.utils.annotated_data import (create_annotated_table,
                                                 ANNOTATED_DATA_SIGNAL_NAME)
from Orange.widgets.utils.itemmodels import TableModel
from Orange.widgets.utils.state_summary import format_summary_details
from Orange.widgets.utils import disconnected
from Orange.widgets.utils.headerview import HeaderView
from Orange.widgets.data.utils.tableview import RichTableView
from Orange.widgets.data.utils import tablesummary as tsummary
from Orange.widgets.settings import Setting
import os
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import widget_positioning, help_management
else:
    from orangecontrib.AAIT.utils import widget_positioning, help_management


SubsetRole = next(OrangeUserRole)


# ---------------------------------------------------------------------------
# Proxy de réordonnancement des lignes
# ---------------------------------------------------------------------------
class RowReorderProxyModel(QAbstractProxyModel):
    """
    Proxy intercalé entre _TableModel et la vue.
    _row_order[i] = index source affiché à la position i.
    Le tri est délégué au source (RichTableModel gère son propre tri interne).
    _row_order est remis à [0..n-1] après chaque tri source.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row_order: List[int] = []

    def setSourceModel(self, source_model):
        super().setSourceModel(source_model)
        if source_model is not None:
            self._row_order = list(range(source_model.rowCount()))
        else:
            self._row_order = []
        self.beginResetModel()
        self.endResetModel()

    def setRowOrder(self, order: List[int]):
        if self.sourceModel() is None:
            return
        n = self.sourceModel().rowCount()
        if sorted(order) == list(range(n)):
            self.beginResetModel()
            self._row_order = list(order)
            self.endResetModel()

    def getRowOrder(self) -> List[int]:
        return list(self._row_order)

    def moveRow(self, from_pos: int, to_pos: int):
        if from_pos == to_pos:
            return
        self.beginResetModel()
        item = self._row_order.pop(from_pos)
        self._row_order.insert(to_pos, item)
        self.endResetModel()

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        src = self.sourceModel()
        if src is None:
            return
        # On délègue au source, puis on remet _row_order à plat.
        # La restauration de l'ordre original est gérée dans le widget
        # en remplaçant le source par un nouveau _TableModel vierge.
        self.beginResetModel()
        src.sort(column, order)
        self._row_order = list(range(src.rowCount()))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid() or self.sourceModel() is None:
            return 0
        return len(self._row_order)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid() or self.sourceModel() is None:
            return 0
        return self.sourceModel().columnCount()

    def mapToSource(self, proxy_index: QModelIndex) -> QModelIndex:
        if not proxy_index.isValid() or self.sourceModel() is None:
            return QModelIndex()
        src_row = self._row_order[proxy_index.row()]
        return self.sourceModel().index(src_row, proxy_index.column())

    def mapFromSource(self, source_index: QModelIndex) -> QModelIndex:
        if not source_index.isValid():
            return QModelIndex()
        try:
            proxy_row = self._row_order.index(source_index.row())
        except ValueError:
            return QModelIndex()
        return self.index(proxy_row, source_index.column())

    def index(self, row, column, parent=QModelIndex()):
        if parent.isValid():
            return QModelIndex()
        return self.createIndex(row, column)

    def parent(self, index=QModelIndex()):
        return QModelIndex()

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        return self.sourceModel().data(self.mapToSource(index), role)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Vertical and self.sourceModel() is not None:
            src_row = self._row_order[section] if section < len(self._row_order) else section
            return self.sourceModel().headerData(src_row, orientation, role)
        if self.sourceModel() is not None:
            return self.sourceModel().headerData(section, orientation, role)
        return None

    def flags(self, index: QModelIndex):
        return self.sourceModel().flags(self.mapToSource(index))


# ---------------------------------------------------------------------------
# Event filter installé sur le VIEWPORT du header vertical
# ---------------------------------------------------------------------------
class RowDragEventFilter(QObject):
    def __init__(self, header: QHeaderView, on_move_callback):
        super().__init__(header)
        self._header = header
        self._on_move = on_move_callback
        self._drag_row: Optional[int] = None
        self._drag_start_y: int = 0
        self._active: bool = False
        self._indicator_row: Optional[int] = None

    def _row_at(self, y: int) -> int:
        return self._header.logicalIndexAt(y)

    def eventFilter(self, obj, event) -> bool:
        t = event.type()

        if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            row = self._row_at(event.pos().y())
            if row >= 0:
                self._drag_row = row
                self._drag_start_y = event.pos().y()
                self._active = False
                self._indicator_row = None
            return False

        elif t == QEvent.MouseMove and (event.buttons() & Qt.LeftButton):
            if self._drag_row is not None:
                dy = abs(event.pos().y() - self._drag_start_y)
                if dy > 6:
                    self._active = True
                if self._active:
                    target = self._row_at(event.pos().y())
                    if target < 0:
                        target = self._header.count() - 1
                    if target != self._indicator_row:
                        self._indicator_row = target
                        self._header.viewport().update()
                    return True

        elif t == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self._drag_row is not None and self._active:
                from_row = self._drag_row
                to_row = self._indicator_row if self._indicator_row is not None else from_row
                self._drag_row = None
                self._active = False
                self._indicator_row = None
                self._header.viewport().update()
                if from_row != to_row:
                    self._on_move(from_row, to_row)
                return True
            self._drag_row = None
            self._active = False
            self._indicator_row = None

        return False


# ---------------------------------------------------------------------------
# Header vertical avec indicateur visuel
# ---------------------------------------------------------------------------
class DraggableVerticalHeader(QHeaderView):
    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self._filter: Optional[RowDragEventFilter] = None
        self.setSectionsClickable(True)
        self.setHighlightSections(True)

    def installDragFilter(self, on_move_callback):
        if self._filter is not None:
            self.viewport().removeEventFilter(self._filter)
        self._filter = RowDragEventFilter(self, on_move_callback)
        self.viewport().installEventFilter(self._filter)

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int):
        super().paintSection(painter, rect, logical_index)
        if self._filter is None or not self._filter._active:
            return
        if logical_index == self._filter._drag_row:
            painter.save()
            painter.fillRect(rect, QColor(60, 120, 255, 45))
            painter.restore()
        if logical_index == self._filter._indicator_row:
            painter.save()
            pen = painter.pen()
            pen.setColor(QColor(60, 120, 255))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
            painter.restore()


class HeaderViewWithSubsetIndicator(HeaderView):
    _IndicatorChar = "\N{BULLET}"

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        opt = QStyleOptionHeader()
        self.initStyleOption(opt)
        self.initStyleOptionForIndex(opt, logicalIndex)
        model = self.model()
        if model is None:
            return
        opt.rect = rect
        issubset = model.headerData(logicalIndex, Qt.Vertical, SubsetRole)
        style = self.style()
        style.drawControl(QStyle.CE_HeaderSection, opt, painter, self)
        indicator_rect = QRect(rect)
        text_rect = QRect(rect)
        indicator_width = opt.fontMetrics.horizontalAdvance(self._IndicatorChar + " ")
        indicator_rect.setWidth(indicator_width)
        text_rect.setLeft(indicator_width)
        if issubset:
            optindicator = QStyleOptionHeader(opt)
            optindicator.rect = indicator_rect
            optindicator.textAlignment = Qt.AlignCenter
            optindicator.text = self._IndicatorChar
            style.drawControl(QStyle.CE_HeaderLabel, optindicator, painter, self)
        opt.rect = text_rect
        style.drawControl(QStyle.CE_HeaderLabel, opt, painter, self)

    def sectionSizeFromContents(self, logicalIndex: int) -> QSize:
        opt = QStyleOptionHeader()
        self.initStyleOption(opt)
        super().initStyleOptionForIndex(opt, logicalIndex)
        opt.text = self._IndicatorChar + " " + opt.text
        return self.style().sizeFromContents(QStyle.CT_HeaderSection, opt, QSize(), self)


class DataTableView(gui.HScrollStepMixin, RichTableView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._install_draggable_header()

    def _install_draggable_header(self):
        vheader = DraggableVerticalHeader(self)
        vheader.setSectionsClickable(True)
        self.setVerticalHeader(vheader)

    def setModel(self, model):
        super().setModel(model)
        if not isinstance(self.verticalHeader(), DraggableVerticalHeader):
            self._install_draggable_header()


class _TableDataDelegate(TableDataDelegate):
    DefaultRoles = TableDataDelegate.DefaultRoles + (SubsetRole,)


class SubsetTableDataDelegate(_TableDataDelegate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subset_opacity = 0.5

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        issubset = self.cachedData(index, SubsetRole)
        opacity = painter.opacity()
        if not issubset:
            painter.setOpacity(self.subset_opacity)
        super().paint(painter, option, index)
        if not issubset:
            painter.setOpacity(opacity)


class TableBarItemDelegate(SubsetTableDataDelegate, gui.TableBarItem, _TableDataDelegate):
    pass


class _TableModel(RichTableModel):
    SubsetRole = SubsetRole

    def __init__(self, *args, subsets=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._subset = subsets or set()

    def setSubsetRowIds(self, subsetids: Container[int]):
        self._subset = subsetids
        if self.rowCount():
            self.headerDataChanged.emit(Qt.Vertical, 0, self.rowCount() - 1)
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
                [SubsetRole],
            )

    def _is_subset(self, row):
        row = self.mapToSourceRows(row)
        try:
            id_ = self.source.ids[row]
        except (IndexError, AttributeError):
            return False
        return int(id_) in self._subset

    def data(self, index: QModelIndex, role=Qt.DisplayRole) -> Any:
        if role == _TableModel.SubsetRole:
            return self._is_subset(index.row())
        return super().data(index, role)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Vertical and role == _TableModel.SubsetRole:
            return self._is_subset(section)
        return super().headerData(section, orientation, role)


@dataclass
class InputData:
    table: Table
    summary: Union[tsummary.Summary, tsummary.ApproxSummary]
    model: TableModel


class _Selection(TypedDict):
    rows: Tuple[int]
    columns: Tuple[int]


_Sorting = List[Tuple[str, int]]


class OWTable(OWWidget):
    name = "Autoshow Data Table"
    description = "View the dataset in a spreadsheet."
    icon = "icons/Table.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/Table.svg"
    category = "AAIT - TOOLBOX"
    priority = 50
    keywords = "data table, view"

    class Inputs:
        data = Input("Data", Table, default=True)
        data_subset = Input("Data Subset", Table)
        input_autoshow = Input("AutoShowConfiguration", str, auto_summary=False)

    class Outputs:
        selected_data = Output("Selected Data", Table, default=True)
        annotated_data = Output(ANNOTATED_DATA_SIGNAL_NAME, Table)

    class Warning(OWWidget.Warning):
        missing_sort_columns = Msg(
            ("Cannot restore sorting.\n" + "Missing columns in input table: {}")
        )
        non_sortable_input = Msg(
            ("Cannot restore sorting.\n" + "Input table cannot be sorted due to implementation constraints.")
        )

    str_WidgetPositionning: str = Setting("None")
    buttons_area_orientation = Qt.Vertical

    show_distributions = Setting(False)
    show_attribute_labels = Setting(True)
    select_rows = Setting(True)
    auto_commit = Setting(True)

    color_by_class = Setting(True)
    stored_selection: _Selection = Setting(
        {"rows": [], "columns": []}, schema_only=True
    )
    stored_sort: _Sorting = Setting([], schema_only=True)
    stored_row_order: List[int] = Setting([], schema_only=True)

    settings_version = 1

    def __init__(self):
        super().__init__()
        self.input: Optional[InputData] = None
        self._subset_ids: Optional[set] = None
        self.__pending_selection: Optional[_Selection] = self.stored_selection
        self.__pending_sort: Optional[_Sorting] = self.stored_sort
        self.__have_new_data = False
        self.__have_new_subset = False
        self.dist_color = QColor(220, 220, 220, 255)

        self._reorder_proxy = RowReorderProxyModel()

        info_box = gui.vBox(self.controlArea, "Info")
        self.info_text = gui.widgetLabel(info_box)

        box = gui.vBox(self.controlArea, "Variables")
        self.c_show_attribute_labels = gui.checkBox(
            box, self, "show_attribute_labels",
            "Show variable labels (if present)",
            callback=self._update_variable_labels)

        gui.checkBox(box, self, "show_distributions",
                     'Visualize numeric values',
                     callback=self._on_distribution_color_changed)
        gui.checkBox(box, self, "color_by_class", 'Color by instance classes',
                     callback=self._on_distribution_color_changed)

        box = gui.vBox(self.controlArea, "Selection")
        gui.checkBox(box, self, "select_rows", "Select full rows",
                     callback=self._on_select_rows_changed)

        gui.rubber(self.controlArea)

        gui.button(self.buttonsArea, self, "Restore Original Order",
                   callback=self.restore_order,
                   tooltip="Show rows in the original order",
                   autoDefault=False,
                   attribute=Qt.WA_LayoutUsesWidgetRect)

        gui.button(self.buttonsArea, self, "Reset Row Order",
                   callback=self._reset_row_order,
                   tooltip="Remet les lignes dans l'ordre d'origine",
                   autoDefault=False,
                   attribute=Qt.WA_LayoutUsesWidgetRect)

        gui.auto_send(self.buttonsArea, self, "auto_commit")

        view = DataTableView(sortingEnabled=True)
        view.setItemDelegate(SubsetTableDataDelegate(view))
        view.selectionFinished.connect(self.update_selection)

        if self.select_rows:
            view.setSelectionBehavior(QTableView.SelectRows)

        header = view.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(-1, Qt.AscendingOrder)
        header.sortIndicatorChanged.connect(
            self._on_sort_indicator_changed, Qt.UniqueConnection
        )

        self.view = view
        self.mainArea.layout().addWidget(self.view)
        self._update_input_summary()
        widget_positioning.show_and_adjust_at_opening(self, str(self.str_WidgetPositionning))
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def copy_to_clipboard(self):
        self.copy()

    def sizeHint(self):
        return QSize(800, 500)

    @Inputs.data
    def set_dataset(self, data: Optional[Table]):
        if data is not None:
            summary = tsummary.table_summary(data)
            self.input = InputData(
                table=data,
                summary=summary,
                model=_TableModel(data)
            )
            if isinstance(summary.len, concurrent.futures.Future):
                def update(_):
                    QMetaObject.invokeMethod(self, "_update_info", Qt.QueuedConnection)
                summary.len.add_done_callback(update)
        else:
            self.input = None
        self.__have_new_data = True

    @Inputs.data_subset
    def set_subset_dataset(self, subset: Optional[Table]):
        if subset is not None and not isinstance(subset, SqlTable):
            ids = set(subset.ids)
        else:
            ids = None
        self._subset_ids = ids
        self.__have_new_subset = True

    @Inputs.input_autoshow
    def set_input_autoshow(self, le_str):
        if le_str is not None:
            self.str_WidgetPositionning = str(le_str)

    def handleNewSignals(self):
        super().handleNewSignals()
        self.Warning.non_sortable_input.clear()
        self.Warning.missing_sort_columns.clear()
        data: Optional[Table] = self.input.table if self.input else None
        model = self.input.model if self.input else None

        if self.__have_new_data:
            self._setup_table_view()
            self._update_input_summary()

            if data is not None and self.__pending_sort is not None:
                self.__restore_sort()

            if data is not None and self.__pending_selection is not None:
                selection = self.__pending_selection
                self.__pending_selection = None
                self.set_selection(selection["rows"], selection["columns"])

        if self.__have_new_subset and model is not None:
            model.setSubsetRowIds(self._subset_ids or set())
            self.__have_new_subset = False

        self._setup_view_delegate()

        if self.__have_new_data:
            if self.auto_commit:
                self.commit.now()
            else:
                self.commit.deferred()
            self.__have_new_data = False

    def _setup_table_view(self):
        if self.input is None:
            self.view.setModel(None)
            return

        datamodel = self.input.model
        datamodel.setSubsetRowIds(self._subset_ids or set())

        self._reorder_proxy.setSourceModel(datamodel)
        if self.stored_row_order:
            self._reorder_proxy.setRowOrder(self.stored_row_order)

        view = self.view
        data = self.input.table
        rowcount = data.approx_len()
        view.setModel(self._reorder_proxy)

        vheader = view.verticalHeader()
        if isinstance(vheader, DraggableVerticalHeader):
            vheader.installDragFilter(self._on_row_moved)

        vheader.setDefaultSectionSize(
            view.style().sizeFromContents(
                QStyle.CT_ItemViewItem, view.viewOptions(), QSize(20, 20), view
            ).height() + 2
        )
        vheader.setMinimumSectionSize(5)
        vheader.setSectionResizeMode(QHeaderView.Fixed)

        maxrows = (2 ** 31 - 1) // (vheader.defaultSectionSize() + 2)
        if rowcount > maxrows:
            sliceproxy = TableSliceProxy(parent=view, rowSlice=slice(0, maxrows))
            sliceproxy.setSourceModel(self._reorder_proxy)
            view.setModel(None)
            view.setModel(sliceproxy)

        assert view.model().rowCount() <= maxrows
        assert vheader.sectionSize(0) > 1 or datamodel.rowCount() == 0

        self._setup_view_delegate()
        self._update_variable_labels()

    def _on_row_moved(self, from_pos: int, to_pos: int):
        self._reorder_proxy.moveRow(from_pos, to_pos)
        self.stored_row_order = self._reorder_proxy.getRowOrder()
        self.commit.deferred()

    def _reset_row_order(self):
        if self.input is None:
            return
        n = self.input.model.rowCount()
        self._reorder_proxy.setRowOrder(list(range(n)))
        self.stored_row_order = []
        self.commit.deferred()

    def _update_input_summary(self):
        def format_summary(summary):
            if isinstance(summary, tsummary.ApproxSummary):
                return summary.len.result() if summary.len.done() else summary.approx_len
            return summary.len

        summary, details = self.info.NoInput, ""
        if self.input:
            summary = format_summary(self.input.summary)
            details = format_summary_details(self.input.table)
        self.info.set_input_summary(summary, details)

        if self.input is None:
            self.info_text.setText("No data.")
        else:
            self.info_text.setText("\n".join(tsummary.format_summary(self.input.summary)))

    def _update_variable_labels(self):
        if self.input is None:
            return
        model = self.input.model
        if self.show_attribute_labels:
            model.setRichHeaderFlags(RichTableModel.Labels | RichTableModel.Name)
        else:
            model.setRichHeaderFlags(RichTableModel.Name)

    def _on_distribution_color_changed(self):
        if self.input is None:
            return
        self._setup_view_delegate()

    def _setup_view_delegate(self):
        if self.input is None:
            return
        model = self.input.model
        data = model.source
        class_var = data.domain.class_var
        if self.color_by_class and class_var and class_var.is_discrete:
            color_schema = [QColor(*c) for c in class_var.colors]
        else:
            color_schema = None
        if self.show_distributions:
            delegate = TableBarItemDelegate(
                self.view, color=self.dist_color, color_schema=color_schema
            )
        else:
            delegate = SubsetTableDataDelegate(self.view)
        delegate.subset_opacity = 0.5 if self._subset_ids is not None else 1.0
        self.view.setItemDelegate(delegate)

    def _on_select_rows_changed(self):
        if self.input is None:
            return
        selection_model = self.view.selectionModel()
        selection_model.setSelectBlocks(not self.select_rows)
        if self.select_rows:
            self.view.setSelectionBehavior(QTableView.SelectRows)
            selection_model.select(
                selection_model.selection(),
                QItemSelectionModel.Select | QItemSelectionModel.Rows
            )
        else:
            self.view.setSelectionBehavior(QTableView.SelectItems)

    def restore_order(self):
        """
        Restaure l'ordre original en recréant un _TableModel vierge
        depuis la Table Orange originale (non triée).
        C'est la seule façon fiable de réinitialiser RichTableModel
        qui maintient son propre état de tri interne.
        """
        if self.input is None:
            return

        # Recrée un modèle source vierge depuis la Table originale
        new_model = _TableModel(self.input.table)
        new_model.setSubsetRowIds(self._subset_ids or set())
        self.input = InputData(
            table=self.input.table,
            summary=self.input.summary,
            model=new_model,
        )

        # Rebrancher le proxy sur le nouveau modèle vierge
        self._reorder_proxy.setSourceModel(new_model)

        # Mettre à jour l'affichage
        if self.show_attribute_labels:
            new_model.setRichHeaderFlags(RichTableModel.Labels | RichTableModel.Name)
        else:
            new_model.setRichHeaderFlags(RichTableModel.Name)

        # Réinstaller le drag filter sur le nouveau modèle
        vheader = self.view.verticalHeader()
        if isinstance(vheader, DraggableVerticalHeader):
            vheader.installDragFilter(self._on_row_moved)

        # Remettre l'indicateur de tri à zéro visuellement
        with disconnected(
            self.view.horizontalHeader().sortIndicatorChanged,
            self._on_sort_indicator_changed,
            Qt.UniqueConnection
        ):
            self.view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)

        self.stored_sort = []
        self.stored_row_order = []
        self.Warning.missing_sort_columns.clear()
        self.commit.deferred()

    @Slot()
    def _update_info(self):
        self._update_input_summary()

    def _on_sort_indicator_changed(self, index: int, order: Qt.SortOrder) -> None:
        if index == -1:
            self.stored_sort = []
        elif self.input is not None:
            model = self.input.model
            coldesc = model.columns[index]
            colid = self.__encode_column_id(coldesc)
            order = -1 if order == Qt.DescendingOrder else 1
            self.stored_sort = [(n, d) for n, d in self.stored_sort if n != colid]
            self.stored_sort.append((colid, order))
        self.update_selection()
        self.Warning.missing_sort_columns.clear()

    def set_sort_columns(self, sorting: List[Tuple[str, int]]):
        if self.input is None:
            return
        self.stored_sort = []
        columns = {id_: i for i, id_ in enumerate(self.__header_ids())}
        with disconnected(self.view.horizontalHeader().sortIndicatorChanged,
                          self._on_sort_indicator_changed, Qt.UniqueConnection):
            for colid, order in sorting:
                if colid in columns:
                    self.view.sortByColumn(
                        columns[colid],
                        Qt.AscendingOrder if order == 1 else Qt.DescendingOrder
                    )
                self.stored_sort.append((colid, order))

    def __restore_sort(self) -> None:
        assert self.input is not None
        sort = self.__pending_sort
        self.__pending_sort = None
        if sort is None:
            return
        if not self.view.isSortingEnabled() and sort:
            self.Warning.non_sortable_input()
            self.Warning.missing_sort_columns.clear()
            return
        columns = {id_: i for i, id_ in enumerate(self.__header_ids())}
        missing_columns = []
        sort_ = []
        for colid, order in sort:
            if colid in columns:
                sort_.append((colid, order))
            else:
                missing_columns.append(self.__decode_column_id(colid))
        self.set_sort_columns(sort_)
        if missing_columns:
            self.Warning.missing_sort_columns(", ".join(missing_columns))

    @staticmethod
    def __encode_column_id(coldesc):
        def escape(s):
            return ("\\" + s) if s.startswith("\\") else s
        if isinstance(coldesc, TableModel.Column):
            return escape(coldesc.var.name)
        lookup = ("TARGET", "META", "FEATURES",)
        return f"\\BASKET({lookup[coldesc.role]})"

    @staticmethod
    def __decode_column_id(cid: str) -> str:
        return cid[1:] if cid.startswith("\\") else cid

    def __header_ids(self) -> List[str]:
        if self.input is None:
            return []
        return [self.__encode_column_id(c) for c in self.input.model.columns]

    @staticmethod
    def _normalize_indices(values):
        if values is None:
            return []

        arr = np.asarray(values)

        if arr.ndim == 0:
            return [int(arr.item())]

        return [int(v) for v in arr.ravel().tolist()]

    def update_selection(self, *_):
        self.commit.deferred()

    def set_selection(self, rows: Sequence[int], columns: Sequence[int]) -> None:
        rows = self._normalize_indices(rows)
        columns = self._normalize_indices(columns)
        self.view.setBlockSelection(rows, columns)

    def get_selection(self):
        rows, cols = self.view.blockSelection()
        # blockSelection() peut retourner des index décalés quand un proxy
        # est intercalé. On prend les rows depuis selectedRows() à la place.
        sel_model = self.view.selectionModel()
        correct_rows = [int(i.row()) for i in sel_model.selectedRows()]
        if correct_rows:
            return correct_rows, self._normalize_indices(cols)
        return self._normalize_indices(rows), self._normalize_indices(cols)

    @gui.deferred
    def commit(self):
        selected_data = table = None
        annotated_rows = []

        if self.input is not None:
            model = self.input.model
            table = self.input.table

            if isinstance(table, SqlTable):
                self.Outputs.selected_data.send(selected_data)
                self.Outputs.annotated_data.send(None)
                return

            rowsel, colsel = self.get_selection()
            self.stored_selection = {"rows": list(rowsel), "columns": list(colsel)}

            domain = table.domain
            if len(colsel) < len(domain.variables) + len(domain.metas):
                allvars = domain.class_vars + domain.metas + domain.attributes
                columns = [(c, model.headerData(c, Qt.Horizontal, TableModel.DomainRole))
                           for c in colsel]
                assert all(role is not None for _, role in columns)

                def select_vars(role):
                    return [allvars[c] for c, r in columns if r == role]

                attrs = select_vars(TableModel.Attribute)
                if attrs and issparse(table.X):
                    attrs = table.domain.attributes
                class_vars = select_vars(TableModel.ClassVar)
                metas = select_vars(TableModel.Meta)
                domain = Orange.data.Domain(attrs, class_vars, metas)

            if rowsel:
                row_order = self._reorder_proxy.getRowOrder()
                proxy_rows = [row_order[r] for r in rowsel if r < len(row_order)]
                src_rows = [int(model.mapToSourceRows(r)) for r in proxy_rows]
                selected_data = table.from_table(domain, table, src_rows)
                annotated_rows = src_rows
            else:
                row_order = self._reorder_proxy.getRowOrder()
                sortsection = self.view.horizontalHeader().sortIndicatorSection()

                if sortsection != -1:
                    src_rows = [int(model.mapToSourceRows(r)) for r in row_order]
                    selected_data = table.from_table(table.domain, table, src_rows)
                else:
                    if row_order and row_order != list(range(len(row_order))):
                        src_rows = [int(model.mapToSourceRows(r)) for r in row_order]
                        selected_data = table.from_table(table.domain, table, src_rows)
                    else:
                        selected_data = table

        self.Outputs.selected_data.send(selected_data)
        self.Outputs.annotated_data.send(
            create_annotated_table(table, annotated_rows) if table is not None else None
        )

    def copy(self):
        if self.input is not None:
            mime = table_selection_to_mime_data(self.view)
            QApplication.clipboard().setMimeData(mime, QClipboard.Clipboard)

    def send_report(self):
        if self.input is None:
            return
        model = self.input.model
        self.report_data_brief(model.source)
        self.report_table(self.view)


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWTable).run(
        input_data=Table("iris"),
    )
