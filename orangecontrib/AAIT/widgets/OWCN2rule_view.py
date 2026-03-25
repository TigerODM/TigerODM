import numpy as np
import re

import os
from AnyQt.QtCore import (
    Qt, QLineF, QSize, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer
)
from AnyQt.QtGui import QPainter, QPen, QBrush, QColor
from AnyQt.QtWidgets import (
    QItemDelegate, QHeaderView, QApplication
)

from Orange.classification.rules import _RuleClassifier
from Orange.widgets import widget, gui, settings
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Input, Output
from Orange.data import Table, Domain, ContinuousVariable, StringVariable

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils import help_management


class OWRuleViewer(widget.OWWidget):
    name = "CN2 Rule Selector"
    description = "Review rules induced from data."
    icon = "icons/CN2RuleViewer.svg"
    category = "AAIT - ALGORITHM"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/CN2RuleViewer.svg"
    priority = 1140
    keywords = "cn2 rule viewer"
    #category="AAIT Resources Manager"
    class Inputs:
        #data = Input("Data", Table)
        point_from_scatter_plot= Input("Point From Scatter Plot", Table)
        classifier = Input("Classifier", _RuleClassifier)

    class Outputs:
#        annotated_data=Output("Annotated Data", Table)
#        selected_data = Output("Selected Data", Table, default=True)
        selected_rule =Output("Selected Rule", Table)


    compact_view = settings.Setting(False)

    want_basic_layout = True
    want_main_area = False
    want_control_area = True

    def __init__(self):
        super().__init__()

        self.data = None
        self.classifier = None
        self.selected = None
        self.data_point_from_scatter_plot =None
        self.model = CustomRuleViewerTableModel(parent=self)
        self.model.set_horizontal_header_labels(
            ["IF conditions", "", "THEN class", "Distribution",
             "Probabilities [%]", "Quality", "Length","number of tested data in rules"])

        self.proxy_model = QSortFilterProxyModel(parent=self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(self.model.SortRole)

        self.view = gui.TableView(self, wordWrap=False)
        self.view.setModel(self.proxy_model)
        self.view.verticalHeader().setVisible(True)
        self.view.horizontalHeader().setStretchLastSection(False)
        self.view.selectionModel().selectionChanged.connect(self.commit)

        self.dist_item_delegate = DistributionItemDelegate(self)
        self.view.setItemDelegateForColumn(3, self.dist_item_delegate)

        self.controlArea.layout().addWidget(self.view)

        gui.checkBox(widget=self.buttonsArea, master=self, value="compact_view",
                     label="Compact view", callback=self.on_update)
        gui.rubber(self.buttonsArea)

        original_order_button = gui.button(
            self.buttonsArea, self,
            "Restore original order",
            autoDefault=False,
            callback=self.restore_original_order,
            attribute=Qt.WA_LayoutUsesWidgetRect,
        )
        original_order_button.clicked.connect(self.restore_original_order)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    # @Inputs.data
    # def set_data(self, data):
    #     self.data = data
    #     self.commit()

    @Inputs.classifier
    def set_classifier(self, classifier):
        self.classifier = classifier
        self.selected = None
        self.model.clear()

        if classifier is not None and hasattr(classifier, "rule_list"):
            self.model.set_vertical_header_labels(
                list(range(len(classifier.rule_list))))

            self.dist_item_delegate.color_schema = \
                [QColor(*c) for c in classifier.domain.class_var.colors]

            self.model.wrap(self.classifier.domain, self.classifier.rule_list)

        self.on_update()
        self.commit()

    @Inputs.point_from_scatter_plot
    def set_new_point_from_scatter_plot(self, data):
        self.data_point_from_scatter_plot = data
        self.on_update()
    def on_update(self):
        self.model.wrap_data_point_from_scatter_plot(self.data_point_from_scatter_plot)
        self._save_selected()

        self.model.set_compact_view(self.compact_view)
        if self.compact_view:
            self.view.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.Interactive)  # QHeaderView.Stretch
        else:
            self.view.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeToContents)
        self.view.resizeColumnsToContents()
        self.view.resizeRowsToContents()

        self._restore_selected()

    def _save_selected(self, actual=False):
        self.selected = None
        selection_model = self.view.selectionModel()
        if selection_model.hasSelection():
            if not actual:
                selection = selection_model.selection()
            else:
                selection = self.proxy_model.mapSelectionToSource(
                    selection_model.selection())

            self.selected = sorted(set(index.row() for index
                                       in selection.indexes()))

    def _restore_selected(self):
        if self.selected is not None:
            selection_model = self.view.selectionModel()
            for row in self.selected:
                selection_model.select(self.proxy_model.index(row, 0),
                                       selection_model.Select |
                                       selection_model.Rows)

    def restore_original_order(self):
        self.proxy_model.sort(-1)

    def copy_to_clipboard(self):
        self._save_selected(actual=True)
        if self.selected is not None:
            output = "\n".join([str(self.classifier.rule_list[i])
                                for i in self.selected])
            QApplication.clipboard().setText(output)

    def commit(self):

        self._save_selected(actual=True)
        # selected_indices = []

        data = self.data or self.classifier and self.classifier.instances
        if (self.selected is not None and
                data is not None and
                self.classifier is not None and
                data.domain.attributes ==
                self.classifier.original_domain.attributes):

            status = np.ones(data.X.shape[0], dtype=bool)
            for i in self.selected:
                rule = self.classifier.rule_list[i]
                status &= rule.evaluate_data(data.X)

            selected_indices = status.nonzero()[0]
            if len(selected_indices)>0:
                if len(status) != len(data):
                    raise ValueError("La longueur de status doit correspondre au nombre de lignes dans data.")

                # status_var = StringVariable("Status")
                # new_domain = Domain(data.domain.attributes, data.domain.class_vars,
                #                     metas=data.domain.metas + (status_var,))
                # outdata_status = Table.from_table(new_domain, data)
                # tab_status=status.reshape(-1, 1)
                # outdata_status[:, "Status"] = tab_status.astype(str)
                # self.Outputs.annotated_data.send(outdata_status)
                # Déclarer la nouvelle variable continue comme attribut
                status_var = ContinuousVariable("Status")
                new_domain = Domain(data.domain.attributes + (status_var,), data.domain.class_vars, data.domain.metas)

                # Créer une nouvelle table basée sur le domaine mis à jour
                outdata_status = Table.from_table(new_domain, data)

                # Convertir "True"/"False" en valeurs continues (1 ou 100)
                tab_status = (status == True).astype(int) * 99 + 1  # True -> 100, False -> 1
                tab_status = tab_status.reshape(-1, 1)

                # Ajouter les valeurs continues à la nouvelle variable
                outdata_status[:, "Status"] = tab_status

                # Envoyer les données modifiées
#                self.Outputs.annotated_data.send(outdata_status)

            # a verifier surement fausse alarme pyflakes
            # data_output = data.from_table_rows(data, selected_indices) \
            #     if len(selected_indices) else None
        if self.classifier!=None:
            if self.selected!=[] and self.selected is not None:
                data = []
                meta = []

                for index_select in self.selected:
                    rule=(self.classifier.rule_list[index_select])
                    regle = str(rule).split(" THEN ")[0]
                    proba = 0
                    if rule.prediction == 0:
                        proba = rule.probabilities[0]
                    else:
                        proba = rule.probabilities[1]
                    data.append([rule.prediction, proba])
                    new_regle=regle
                    if len(new_regle)>3:
                        if new_regle[:3]=="IF ":
                            new_regle=new_regle[3:]
                    # meta.append(new_regle)
                    new_regle=new_regle.replace(" AND ", " and ")
                    #meta.append([regle.replace("IF", "").replace("THEN", "").replace("_", "").replace(" AND ", " and ")])
                    meta.append([new_regle])
                # header = ['prediction', 'quality']
                domain = Domain([ContinuousVariable('prediction'), ContinuousVariable('proba')],
                                metas=[StringVariable('regle')])

                # domain = Domain([ContinuousVariable('prediction'), ContinuousVariable('proba'), DiscreteVariable('regle', values=meta)] )
                out_data = Table.from_numpy(domain, data, metas=meta)
                self.Outputs.selected_rule.send(out_data)
#        self.Outputs.selected_data.send(data_output)


    def send_report(self):
        if self.classifier is not None:
            self.report_table("Induced rules", self.view)

    def sizeHint(self):
        return QSize(800, 450)


class CustomRuleViewerTableModel(QAbstractTableModel):
    SortRole = Qt.UserRole + 1

    # ascii operators
    OPERATORS = {
        '==': '=',
        '!=': '≠',
        '<=': '≤',
        '>=': '≥'
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._domain = None
        self._rule_list = []
        self._compact_view = False
        self._headers = {}
        self._data_point_from_scatter_plot=None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            headers = self._headers.get(orientation)
            return (headers[section] if headers and section < len(headers)
                    else str(section))
        return None

    def del_space_debut_fin(self, text_to_edit):
        if text_to_edit[0] == " ":
            text_to_edit = text_to_edit[1:]
        if text_to_edit[-1] == " ":
            text_to_edit = text_to_edit[:-1]
        return text_to_edit

    def set_horizontal_header_labels(self, labels):
        self._headers[Qt.Horizontal] = labels

    def set_vertical_header_labels(self, labels):
        self._headers[Qt.Vertical] = labels

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._headers[Qt.Horizontal])

    def wrap(self, domain, rule_list):
        self.beginResetModel()
        self._domain = domain
        self._rule_list = rule_list
        self.endResetModel()
    def wrap_data_point_from_scatter_plot(self,data_point_from_scatter_plot):
        self._data_point_from_scatter_plot=data_point_from_scatter_plot
    def clear(self):
        self.beginResetModel()
        self._domain = None
        self._rule_list = []
        self.endResetModel()

    def set_compact_view(self, compact_view):
        self.beginResetModel()
        self._compact_view = compact_view
        self.endResetModel()

    def data(self, index, role=Qt.DisplayRole):
        if self._domain is None or not index.isValid():
            return None

        def _display_role():
            if column == 0:
                delim = " AND " if self._compact_view else " AND\n"
                return "TRUE" if not rule.selectors else delim.join(
                    [attributes[s.column].name + self.OPERATORS[s.op] +
                     (attributes[s.column].values[int(s.value)]
                      if attributes[s.column].is_discrete
                      else str(s.value)) for s in rule.selectors])
            if column == 1:
                return '→'
            if column == 2:
                return class_var.name + "=" + class_var.values[rule.prediction]
            if column == 3:
                # type(curr_class_dist) = ndarray
                return ([float(format(x, '.1f')) for x in rule.curr_class_dist]
                        if rule.curr_class_dist.dtype == float
                        else rule.curr_class_dist.tolist())
            if column == 4:
                return " : ".join(str(int(round(100 * x)))
                                  for x in rule.probabilities)
            if column == 5:
                value = rule.quality
                absval = abs(value)
                strlen = len(str(int(absval)))
                return '{:.{}{}}'.format(value,
                                         2 if absval < .001 else
                                         3 if strlen < 2 else
                                         1 if strlen < 5 else
                                         0 if strlen < 6 else
                                         3,
                                         'f' if (absval == 0 or
                                                 absval >= .001 and
                                                 strlen < 6)
                                         else 'e')
            if column == 6:
                return rule.length
            if column == 7:
                if self._data_point_from_scatter_plot==None:
                    return 0
                if len(self._data_point_from_scatter_plot)==0:
                    return 0
                input_selected_data = self._data_point_from_scatter_plot
                line=str(rule)
                line =line[3:]# remove IF
                current_rules=line.split(" THEN ")[0]
                if current_rules == "TRUE":
                    return len(input_selected_data)
                regl_list = current_rules.split(" AND ")
                regle_a_tester = []
                for unit_rule in regl_list:
                    current_var, current_symb, current_value = re.split(r'(<=|>=)', unit_rule)
                    current_var = self.del_space_debut_fin(current_var)
                    current_symb = self.del_space_debut_fin(current_symb)
                    current_value = float(self.del_space_debut_fin(current_value))
                    regle_a_tester.append([current_var, current_symb, current_value])
                nb_dedans = 0
                for la_data in input_selected_data:
                    dedans = True
                    for regl in regle_a_tester:
                        if dedans == False:
                            break
                        if regl[1] == ">=":
                            if la_data[la_data.domain.index(regl[0])].value <= regl[2]:
                                dedans = False
                        else:
                            if la_data[la_data.domain.index(regl[0])].value >= regl[2]:
                                dedans = False
                    if dedans:
                        nb_dedans = nb_dedans + 1
                return nb_dedans



                return 0

            return None

        def _tooltip_role():
            if column == 0:
                return _display_role().replace(" AND ", " AND\n")
            if column == 1:
                return None
            if column == 3:
                # list of int, float
                curr_class_dist = _display_role()
                return class_var.name + "\n" + "\n".join(
                    (str(curr_class) + ": " + str(curr_class_dist[i])
                     for i, curr_class in enumerate(class_var.values)))
            if column == 4:
                return class_var.name + "\n" + "\n".join(
                    str(curr_class) + ": " +
                    '{:.1f}'.format(rule.probabilities[i] * 100) + "%"
                    for i, curr_class in enumerate(class_var.values))
            return _display_role()

        def _sort_role():
            if column == 0:
                return rule.length
            if column == 3:
                # return int, not np.int!
                return int(sum(rule.curr_class_dist))
            return _display_role()

        attributes = self._domain.attributes
        class_var = self._domain.class_var
        rule = self._rule_list[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            return _display_role()
        if role == Qt.ToolTipRole:
            return _tooltip_role()
        if role == self.SortRole:
            return _sort_role()
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignVCenter | [(Qt.AlignRight if self._compact_view
                                        else Qt.AlignLeft), Qt.AlignCenter,
                                       Qt.AlignLeft, Qt.AlignCenter,
                                       Qt.AlignCenter, Qt.AlignRight,
                                       Qt.AlignRight,Qt.AlignRight][column])

    def __len__(self):
        return len(self._rule_list)

    def __bool__(self):
        return len(self) != 0

    def __iter__(self):
        return iter(self._rule_list)

    def __getitem__(self, item):
        return self._rule_list[item]


class DistributionItemDelegate(QItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.color_schema = None

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setWidth(size.width() + 10)
        return size

    def paint(self, painter, option, index):
        curr_class_dist = np.array(index.data(Qt.DisplayRole), dtype=float)
        curr_class_dist /= sum(curr_class_dist)
        painter.save()
        self.drawBackground(painter, option, index)
        rect = option.rect

        if sum(curr_class_dist) > 0:
            pw = 3
            hmargin = 5
            x = rect.left() + hmargin
            width = rect.width() - 2 * hmargin
            vmargin = 1
            textoffset = pw + vmargin * 2
            painter.save()
            baseline = rect.bottom() - textoffset / 2

            text = str(index.data(Qt.DisplayRole))
            option.displayAlignment = Qt.AlignCenter
            text_rect = rect.adjusted(0, 0, 0, -textoffset*0)
            self.drawDisplay(painter, option, text_rect, text)

            painter.setRenderHint(QPainter.Antialiasing)
            for prop, color in zip(curr_class_dist, self.color_schema):
                if prop == 0:
                    continue
                painter.setPen(QPen(QBrush(color), pw))
                to_x = x + prop * width
                line = QLineF(x, baseline, to_x, baseline)
                painter.drawLine(line)
                x = to_x
            painter.restore()

        painter.restore()


if __name__ == "__main__":  # pragma: no cover
    from Orange.classification import CN2Learner
    data = Table("iris")
    learner = CN2Learner()
    model = learner(data)
    model.instances = data
    WidgetPreview(OWRuleViewer).run(model)
