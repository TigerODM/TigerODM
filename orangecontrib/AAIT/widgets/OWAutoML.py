# installer  flaml 2.8.0 et lightgbm 4.7.0

import os
import pickle
import re

import Orange.data
from Orange.base import Model, Learner
from Orange.evaluation import Results
from Orange.widgets import widget
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import Qt, QTimer
from AnyQt.QtGui import QBrush, QColor, QFont
from AnyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                             QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.automl import automl_functions
    from Orange.widgets.orangecontrib.AAIT.utils.automl.orange_automl import estimator_label
    from Orange.widgets.orangecontrib.AAIT.utils.automl import help_texts
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils.automl import automl_functions
    from orangecontrib.AAIT.utils.automl.orange_automl import estimator_label
    from orangecontrib.AAIT.utils.automl import help_texts
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


RESULT_INDEX_ROLE = Qt.UserRole + 1


class NumericItem(QTableWidgetItem):
    """Table item sorted by its numeric value (NaN last)."""
    def __init__(self, value, fmt="{:.4f}"):
        value = float(value)
        text = "" if value != value else (str(int(value)) if fmt == "{:d}" else fmt.format(value))
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        if isinstance(other, NumericItem):
            a, b = self.value, other.value
            if a != a or b != b:
                # empty values (e.g. "not trained" rows) stay at the bottom in BOTH sort orders
                table = self.tableWidget()
                descending = table is not None and \
                    table.horizontalHeader().sortIndicatorOrder() == Qt.DescendingOrder
                if a != a and b != b:
                    return False
                return (a != a) == descending
            return a < b
        return super().__lt__(other)


MODEL_COLUMN_WIDTH = 320


def model_name_item(label, frozen=False):
    """Model name cell: full name in the tooltip (stacking names can be very long)."""
    item = QTableWidgetItem(label)
    item.setToolTip(label + ("<br><br>" + help_texts.REFERENCE_HELP if frozen else ""))
    if frozen:
        item.setBackground(QBrush(QColor(220, 230, 250)))
    return item


def set_header_tooltips(table):
    """Explain every column (what the statistic is and what it is used for)."""
    for col in range(table.columnCount()):
        item = table.horizontalHeaderItem(col)
        if item is not None:
            item.setToolTip(help_texts.column_help(item.text()))


def size_columns(table, model_column):
    """Fit the columns to their content, but cap the model name column."""
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setStretchLastSection(True)
    table.resizeColumnsToContents()
    header.setSectionResizeMode(model_column, QHeaderView.Interactive)
    table.setColumnWidth(model_column, min(table.columnWidth(model_column), MODEL_COLUMN_WIDTH))
    table.setTextElideMode(Qt.ElideRight)


HIGHER_IS_BETTER = {"Accuracy", "Weighted F1", "F1", "Precision", "Recall", "AUC", "R2"}
DRIFT_WARNING, DRIFT_ALERT = 0.05, 0.15  # relative degradation CV -> validation


def relative_degradation(metric, reference, value):
    """
    > 0 when `value` is worse than `reference`, relative to the larger of the two
    (stays bounded when one of them is 0, e.g. a train RMSE of 0 for k-NN).
    """
    if reference != reference or value != value:
        return float("nan")
    denom = max(abs(reference), abs(value), 1e-12)
    return (reference - value) / denom if metric in HIGHER_IS_BETTER else (value - reference) / denom


class ValidationDialog(QDialog):
    """Window showing the hold-out validation scores next to the train and CV ones."""

    def __init__(self, parent, validation):
        super().__init__(parent)
        self.owner = parent  # the AutoML widget (export logic, folder setting)
        self.validation = validation
        self.setWindowTitle("AutoML - evaluation on validation data")
        self.resize(1100, 520)
        layout = QVBoxLayout(self)

        v = validation
        info = (f"Models re-trained on all the <b>{v['n_train']}</b> training rows, then scored on the "
                f"<b>{v['n_used']}</b> validation rows (never used by the search nor the cross-validation).<br>"
                f"<b>Train</b>: score on the training data itself (optimistic). "
                f"<b>CV</b>: 5-fold cross-validation. <b>Validation</b>: hold-out score (the most honest). "
                f"<b>Drift</b>: degradation from CV to validation "
                f"(<span style='color:#c77c00'>&gt; {DRIFT_WARNING:.0%}</span>, "
                f"<span style='color:#c00000'>&gt; {DRIFT_ALERT:.0%}</span>: over-fitting or data shift).<br>"
                f"Select models (Ctrl / Shift) and export them: they are trained on all the training data, "
                f"never on the validation data.")
        warnings = []
        if v["overlap"]:
            warnings.append(f"{v['overlap']} validation rows are also in the training data: "
                            f"the validation score is optimistic.")
        if v["missing_features"]:
            warnings.append("Features missing in the validation data (imputed): "
                            + ", ".join(v["missing_features"][:10]) + ("..." if len(v["missing_features"]) > 10 else ""))
        if v["n_unknown_class"]:
            warnings.append(f"{v['n_unknown_class']} validation rows have a class unknown to the models (counted as errors).")
        if warnings:
            info += "<br><span style='color:#c00000'>⚠ " + "<br>⚠ ".join(warnings) + "</span>"
        label = QLabel(info)
        label.setWordWrap(True)
        layout.addWidget(label)

        row = QHBoxLayout()
        row.addWidget(QLabel("Metric:"))
        self.combo = QComboBox()
        self.metric_names = automl_functions.metric_names(v["is_classification"])
        self.combo.addItems(self.metric_names)
        for i, n in enumerate(self.metric_names):
            self.combo.setItemData(i, help_texts.METRIC_HELP.get(n, ""), Qt.ToolTipRole)
        self.combo.setCurrentText("Weighted F1" if v["is_classification"] else "RMSE")
        self.combo.currentTextChanged.connect(self.fill)
        row.addWidget(self.combo)
        row.addStretch(1)
        layout.addLayout(row)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.update_export_button)
        layout.addWidget(self.table)

        # export of the selected models (trained on all the training data, not on the validation data)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Export folder:"))
        self.line_folder = QLineEdit(getattr(self.owner, "export_folder", ""))
        self.line_folder.setReadOnly(True)
        self.line_folder.setPlaceholderText("Choose a folder...")
        bottom.addWidget(self.line_folder, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self.owner.browse_folder(self))
        bottom.addWidget(browse)
        self.button_export = QPushButton("Export selected models")
        self.button_export.setEnabled(False)
        self.button_export.setToolTip(help_texts.PARAM_HELP["export_from_validation"])
        self.button_export.clicked.connect(self.export_selected)
        bottom.addWidget(self.button_export)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.fill()

    def selected_entries(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        indexes = [self.table.item(r, 0).data(RESULT_INDEX_ROLE) for r in rows]
        return [self.validation["rows"][i]["entry"] for i in indexes if i is not None]

    def update_export_button(self):
        self.button_export.setEnabled(bool(self.selected_entries()))

    def export_selected(self):
        entries = self.selected_entries()
        current = (self.owner.automl_result or {}).get("results", [])
        if not entries or not all(any(e is c for c in current) for e in entries):
            QMessageBox.warning(self, "AutoML export",
                                "The AutoML results have changed since this evaluation "
                                "(new data or new run): evaluate again before exporting.")
            return
        self.owner.export_entries(entries, parent=self)

    def fill(self, *_):
        m = self.combo.currentText()
        others = [n for n in self.metric_names if n != m]
        headers = ["Model", f"Train {m}", f"CV {m}", f"CV {m} std", f"Validation {m}", f"Val {m} 95% CI",
                   "Drift CV→Val", "Train−CV gap"] + [f"Val {n}" for n in others]
        val_col, drift_col = 4, 6
        rows = self.validation["rows"]
        table = self.table
        table.setSortingEnabled(False)
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        set_header_tooltips(table)
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            train, cv, val = r["train"][m], r["cv"][m], r["validation"][m]
            drift = relative_degradation(m, cv, val)
            gap = relative_degradation(m, train, cv)
            low, high = r["validation_ci"].get(m, (float("nan"), float("nan")))
            ci = NumericItem(low)  # sorted by the lower bound
            ci.setText("" if low != low else f"[{low:.4f} ; {high:.4f}]")
            name = model_name_item(("★ " if r["one_se_pick"] else "") + r["label"],
                                   r["entry"].get("frozen", False))
            name.setData(RESULT_INDEX_ROLE, i)
            if r["one_se_pick"]:
                name.setToolTip(r["label"] + "<br><br>" + help_texts.COLUMN_HELP["1-SE rule"])
            cells = [name, NumericItem(train), NumericItem(cv), NumericItem(r["cv_std"].get(m, float("nan"))),
                     NumericItem(val), ci,
                     NumericItem(100 * drift, "{:+.1f} %"), NumericItem(100 * gap, "{:+.1f} %")]
            cells += [NumericItem(r["validation"][n]) for n in others]
            color = None
            if drift == drift and drift > DRIFT_ALERT:
                color = QColor(255, 190, 190)
            elif drift == drift and drift > DRIFT_WARNING:
                color = QColor(255, 225, 170)
            for col, item in enumerate(cells):
                if color is not None and col in (val_col, drift_col):
                    item.setBackground(QBrush(color))
                table.setItem(i, col, item)
        table.setSortingEnabled(True)
        # best validation score first
        table.sortByColumn(val_col, Qt.DescendingOrder if m in HIGHER_IS_BETTER else Qt.AscendingOrder)
        size_columns(table, model_column=0)


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWAutoML(widget.OWWidget):
    name = "AutoML"
    description = ("Automatic machine learning with FLAML (CPU): tests several algorithms, tunes their "
                   "hyper-parameters and combines the best ones. Classification if the target is categorical, "
                   "regression if it is numeric.")
    category = "AAIT - ALGORITHM"
    icon = "icons/owautoml.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owautoml.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owautoml.ui")
    want_control_area = False
    priority = 1230
    keywords = ["automl", "flaml", "machine learning", "classification", "regression", "hyperparameter"]

    # Settings
    time_budget: int = Setting(60)
    n_jobs: int = Setting(max(1, (os.cpu_count() or 2) - 1))
    metric_classification: str = Setting("macro_f1")
    metric_regression: str = Setting("rmse")
    ensemble: bool = Setting(True)
    stacking: bool = Setting(True)
    zero_shot: bool = Setting(False)
    unchecked_estimators: list = Setting(list(automl_functions.DEFAULT_UNCHECKED))
    export_folder: str = Setting("")
    extra_time: int = Setting(60)

    class Inputs:
        data = Input("Data", Orange.data.Table)
        # hold-out data: never used by the search nor the cross-validation
        validation = Input("Validation Data", Orange.data.Table)
        # optional model with a FROZEN architecture, compared with the FLAML models
        reference = Input("Reference Model", Model, auto_summary=False)

    class Outputs:
        model = Output("Model", Model)
        learner = Output("Learner", Learner, auto_summary=False)
        predictions = Output("Predictions", Orange.data.Table)
        evaluation_results = Output("Evaluation Results", Results)
        leaderboard = Output("Leaderboard", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.cancel_running()
        self.data = in_data
        self.automl_result = None
        self.fill_results_table()
        self.Outputs.model.send(None)
        self.Outputs.learner.send(None)
        self.Outputs.predictions.send(None)
        self.Outputs.evaluation_results.send(None)
        self.Outputs.leaderboard.send(None)
        self.update_task_ui()
        self.update_validation_ui()

    @Inputs.reference
    def set_reference(self, model):
        self.reference_model = model
        self.update_reference_ui()

    @Inputs.validation
    def set_validation(self, in_data):
        self.validation_data = in_data
        self.update_validation_ui()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setMinimumWidth(780)
        self.setMinimumHeight(640)
        self.form = uic.loadUi(self.gui)
        self.mainArea.layout().addWidget(self.form)

        self.label_info = self.findChild(QLabel, "label_info")
        self.label_reference = self.findChild(QLabel, "label_reference")
        self.label_status = self.findChild(QLabel, "label_status")
        self.spin_time = self.findChild(QSpinBox, "spin_time")
        self.spin_threads = self.findChild(QSpinBox, "spin_threads")
        self.combo_metric = self.findChild(QComboBox, "combo_metric")
        self.check_ensemble = self.findChild(QCheckBox, "check_ensemble")
        self.check_stacking = self.findChild(QCheckBox, "check_stacking")
        self.check_zero_shot = self.findChild(QCheckBox, "check_zero_shot")
        self.list_estimators = self.findChild(QListWidget, "list_estimators")
        self.button_check_all = self.findChild(QPushButton, "pushButton_check_all")
        self.button_run = self.findChild(QPushButton, "pushButton_run")
        self.button_continue = self.findChild(QPushButton, "pushButton_continue")
        self.spin_extra = self.findChild(QSpinBox, "spin_extra")
        self.button_export = self.findChild(QPushButton, "pushButton_export")
        self.button_browse = self.findChild(QPushButton, "pushButton_browse")
        self.line_folder = self.findChild(QLineEdit, "lineEdit_folder")
        self.table_results = self.findChild(QTableWidget, "table_results")
        self.label_validation = self.findChild(QLabel, "label_validation")
        self.button_validate = self.findChild(QPushButton, "pushButton_validate")
        self.line_folder.setText(self.export_folder)

        self.spin_time.setValue(int(self.time_budget))
        self.spin_time.valueChanged.connect(lambda v: setattr(self, "time_budget", int(v)))
        self.spin_threads.setMaximum(max(1, os.cpu_count() or 1))
        self.spin_threads.setValue(int(self.n_jobs))
        self.spin_threads.valueChanged.connect(lambda v: setattr(self, "n_jobs", int(v)))
        self.check_ensemble.setChecked(bool(self.ensemble))
        self.check_ensemble.toggled.connect(lambda b: setattr(self, "ensemble", bool(b)))
        self.check_stacking.setChecked(bool(self.stacking))
        self.check_stacking.toggled.connect(lambda b: setattr(self, "stacking", bool(b)))
        self.check_zero_shot.setChecked(bool(self.zero_shot))
        self.check_zero_shot.toggled.connect(lambda b: setattr(self, "zero_shot", bool(b)))
        self.combo_metric.currentTextChanged.connect(self.update_metric)
        self.list_estimators.itemChanged.connect(self.update_estimators)
        self.button_check_all.clicked.connect(lambda: self.toggle_all_estimators())

        self.table_results.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table_results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_results.verticalHeader().setVisible(False)
        self.table_results.setSortingEnabled(True)  # click on a header to sort
        self.table_results.itemSelectionChanged.connect(self.on_selection_changed)

        self.button_run.clicked.connect(lambda: self.run())
        self.button_continue.clicked.connect(lambda: self.continue_search())
        self.spin_extra.setValue(int(self.extra_time))
        self.spin_extra.valueChanged.connect(lambda v: setattr(self, "extra_time", int(v)))
        self.button_browse.clicked.connect(self.browse_folder)
        self.button_export.clicked.connect(self.export_selected_models)
        self.button_validate.clicked.connect(self.evaluate_on_validation)

        # Data Management
        self.data = None
        self.validation_data = None
        self.reference_model = None
        self.validation_dialog = None
        self.is_classification = None
        self.automl_result = None
        self.thread = None
        self.fit_thread = None
        self.pending_fit = None
        self.run_id = 0
        for object_name, tip in help_texts.PARAM_HELP.items():
            child = self.findChild(QWidget, object_name)
            if child is not None:
                child.setToolTip(tip)
        self.update_task_ui()
        self.post_initialized()

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    # ------------------------------------------------------------------ UI
    def update_task_ui(self):
        self.error("")
        self.is_classification, msg = automl_functions.get_task_info(self.data)
        if self.data is None:
            self.label_info.setText("No data on input.")
        elif self.is_classification is None:
            self.label_info.setText(msg)
            self.error(msg)
        else:
            target = self.data.domain.class_var
            if self.is_classification:
                txt = (f"Target <b>{target.name}</b> is categorical ({len(target.values)} classes) "
                       f"→ <b>classification</b> (metrics: Accuracy, Weighted F1, F1, Precision, Recall, AUC).")
            else:
                txt = f"Target <b>{target.name}</b> is numeric → <b>regression</b> (metrics: RMSE, MAE, R²)."
            self.label_info.setText(f"{txt}<br>{len(self.data)} rows, "
                                    f"{len(self.data.domain.attributes)} features.")

        is_classif = self.is_classification if self.is_classification is not None else True
        # metrics
        self.combo_metric.blockSignals(True)
        self.combo_metric.clear()
        metrics = automl_functions.CLASSIFICATION_METRICS if is_classif else automl_functions.REGRESSION_METRICS
        self.combo_metric.addItems(metrics)
        for i, name in enumerate(metrics):
            self.combo_metric.setItemData(i, help_texts.OPTIMISATION_METRIC_HELP.get(name, ""), Qt.ToolTipRole)
        current = self.metric_classification if is_classif else self.metric_regression
        if current in metrics:
            self.combo_metric.setCurrentText(current)
        self.combo_metric.blockSignals(False)
        # estimators
        self.list_estimators.blockSignals(True)
        self.list_estimators.clear()
        for name in automl_functions.available_estimators(is_classif):
            item = QListWidgetItem(estimator_label(name))
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if name in self.unchecked_estimators else Qt.Checked)
            self.list_estimators.addItem(item)
        self.list_estimators.blockSignals(False)
        self.update_check_all_button()
        self.button_run.setEnabled(self.is_classification is not None)
        self.update_reference_ui()

    def update_reference_ui(self):
        model = self.reference_model
        if model is None:
            self.label_reference.setText('No reference model (optional "Reference Model" input, '
                                         'e.g. from Load Model).')
            return
        message = automl_functions.check_reference_model(model, self.data)
        name = getattr(model, "name", None) or type(model).__name__
        if message:
            self.label_reference.setText(f"<span style='color:#c00000'>⚠ Reference model <b>{name}</b> "
                                         f"ignored: {message}</span>")
            return
        text = (f"<b>[frozen]</b> Reference model <b>{name}</b>: <b>frozen architecture</b> (same algorithm and "
                f"hyper-parameters, not tuned) - re-trained and cross-validated on the current data, "
                f"then compared with the FLAML models.")
        current = [r for r in (self.automl_result or {}).get("results", []) if r["name"] == "reference"]
        if self.automl_result and not (current and current[0].get("reference_model") is model):
            text += " <i>Run or continue the search to include it.</i>"
        self.label_reference.setText(text)

    def update_metric(self, text):
        if not text:
            return
        if self.is_classification is False:
            self.metric_regression = text
        else:
            self.metric_classification = text

    def update_estimators(self, _item=None):
        unchecked = set(self.unchecked_estimators)
        for i in range(self.list_estimators.count()):
            item = self.list_estimators.item(i)
            name = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked:
                unchecked.discard(name)
            else:
                unchecked.add(name)
        self.unchecked_estimators = sorted(unchecked)
        self.update_check_all_button()

    def all_estimators_checked(self):
        items = [self.list_estimators.item(i) for i in range(self.list_estimators.count())]
        return bool(items) and all(it.checkState() == Qt.Checked for it in items)

    def toggle_all_estimators(self):
        """Check all the algorithms, or uncheck them all if they are all checked."""
        state = Qt.Unchecked if self.all_estimators_checked() else Qt.Checked
        self.list_estimators.blockSignals(True)
        for i in range(self.list_estimators.count()):
            self.list_estimators.item(i).setCheckState(state)
        self.list_estimators.blockSignals(False)
        self.update_estimators()

    def update_check_all_button(self):
        self.button_check_all.setText("Uncheck all" if self.all_estimators_checked() else "Check all")

    def checked_estimators(self):
        return [self.list_estimators.item(i).data(Qt.UserRole)
                for i in range(self.list_estimators.count())
                if self.list_estimators.item(i).checkState() == Qt.Checked]

    # ------------------------------------------------------------------ Run
    def cancel_running(self):
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop = True  # the result of this thread will be ignored
        self.pending_fit = None
        self.run_id += 1
        self.set_running(False)

    def set_running(self, running):
        self.running = running
        self.button_run.setEnabled(not running and self.is_classification is not None)
        self.button_run.setText("Running..." if running else "Run AutoML")
        self.update_continue_ui()

    def update_continue_ui(self):
        self.button_continue.setEnabled(bool(self.automl_result) and not getattr(self, "running", False))

    def continue_search(self):
        """Give more time to the search of the CHECKED algorithms, starting from their best configs."""
        if not self.automl_result:
            return
        self.run(previous=self.automl_result)

    def run(self, previous=None):
        self.error("")
        self.warning("")
        if self.data is None or self.is_classification is None:
            return
        estimators = self.checked_estimators()
        if not estimators:
            self.error("Select at least one algorithm.")
            return
        previous_running = self.thread is not None and self.thread.isRunning()
        if previous_running and not self.thread.stop:
            return  # a run is already in progress

        self.run_id += 1
        run_id = self.run_id
        time_budget = int(self.extra_time if previous else self.time_budget)
        if previous is None:
            self.automl_result = None
            self.fill_results_table()
        # (when continuing, the current results stay visible until the new ones arrive)
        self.set_running(True)
        # a cancelled run still finishes its current FLAML trial; the new one waits for it
        if previous_running:
            self.label_status.setText("Stopping the previous run, then searching...")
        elif previous is not None:
            self.label_status.setText(f"Continuing the search (+{time_budget} s) on {len(estimators)} "
                                      f"checked algorithm(s); the others are kept as they are...")
        else:
            self.label_status.setText(f"Searching ({time_budget} s max)...")
        self.progressBarInit()

        self.thread = thread_management.Thread(
            automl_functions.run_automl, self.data,
            time_budget=time_budget, n_jobs=int(self.n_jobs),
            estimator_list=estimators, metric=self.combo_metric.currentText(),
            ensemble=bool(self.ensemble), stacking=bool(self.stacking), previous=previous,
            reference_model=self.reference_model, zero_shot=bool(self.zero_shot))
        self.thread.progress.connect(lambda v, rid=run_id: rid == self.run_id and self.handle_progress(v))
        self.thread.result.connect(lambda r, rid=run_id: rid == self.run_id and self.handle_result(r))
        self.thread.error.connect(lambda e, rid=run_id: rid == self.run_id and self.handle_error(e))
        self.thread.finish.connect(lambda rid=run_id: rid == self.run_id and self.handle_finish())
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)
        if value >= 80:
            self.label_status.setText(f"Cross-validation of the best models... ({value:.0f} %)")

    def handle_result(self, result):
        if result is None:
            return  # cancelled run
        try:
            self.automl_result = result
            self.fill_results_table()
            # cross-validated predictions, like Test & Score
            self.Outputs.evaluation_results.send(result["evaluation_results"])
            self.Outputs.predictions.send(automl_functions.predictions_table(result))
            self.Outputs.leaderboard.send(automl_functions.leaderboard_table(result))
            self.select_result_index(0)  # best model by default
            r = result["results"]
            run_info = ""
            if result["n_runs"] > 1:
                counts = {}
                for e in r:
                    counts[e.get("run_status", "")] = counts.get(e.get("run_status", ""), 0) + 1
                run_info = (f"Run {result['n_runs']} (+{result['total_time']:.0f} s, "
                            f"{result['cumulative_time']:.0f} s in total): "
                            + ", ".join(f"{n} {k}" for k, n in counts.items() if k) + ". ")
            self.label_status.setText(run_info + f"{len(r)} models in {result['total_time']:.0f} s "
                                      f"(search {result['search_time']:.0f} s). "
                                      f"Best ({result['ranking_metric']}): {r[0]['label']}. "
                                      f"1-SE rule recommends: {result['one_se']['label']} "
                                      f"({result['one_se']['n_within']} model(s) statistically as good as the best)."
                                      + (" Zero-shot start: " + ", ".join(estimator_label(n) for n in result["zero_shot"])
                                         + "." if result.get("zero_shot") else ""))
            untrained = [e["label"] for e in r if e.get("untrained")]
            others = [s for s in result["skipped"]
                      if not any(s.startswith(label) for label in untrained)]  # e.g. kept models, reference
            parts = []
            if untrained:
                parts.append(f"{len(untrained)} checked algorithm(s) not trained (listed at the bottom of "
                             f"the table): " + ", ".join(untrained))
            if others:
                parts.append("Not evaluated: " + ", ".join(others))
            if parts:
                self.warning(". ".join(parts) + ". Increase the time out or use Continue search.")
        except Exception as e:
            print("An error occurred when sending AutoML results:", e)
            self.error(str(e))
            self.Outputs.model.send(None)

    def handle_error(self, message):
        self.error(message)
        self.label_status.setText("")

    def handle_finish(self):
        print("AutoML finished")
        # the training on all data of the selected model may already use the progress bar
        if self.fit_thread is None or not self.fit_thread.isRunning():
            self.progressBarFinished()
        self.set_running(False)

    # ------------------------------------------------------------------ Results
    def fill_results_table(self):
        table = self.table_results
        table.setSortingEnabled(False)
        table.clear()
        table.setRowCount(0)
        self.button_export.setEnabled(False)
        if not self.automl_result:
            table.setColumnCount(0)
            table.setSortingEnabled(True)
            return
        res = self.automl_result
        names = automl_functions.metric_names(res["is_classification"])
        rank = res["ranking_metric"]
        continued = res.get("n_runs", 1) > 1
        headers = ["#", "Model"] + names + [f"{rank} std", "1-SE rule"] \
            + (["Last run", f"Δ {rank}"] if continued else []) + ["CV time (s)", "Configuration"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        set_header_tooltips(table)
        table.setRowCount(len(res["results"]))
        bold = QFont()
        bold.setBold(True)
        for row, r in enumerate(res["results"]):
            cells = [NumericItem(row + 1, "{:d}"), model_name_item(r["label"], r.get("frozen", False))]
            cells += [NumericItem(r["metrics"][n]) for n in names]
            one_se = QTableWidgetItem("★ recommended" if r.get("one_se_pick")
                                      else "≈ best" if r.get("within_1se") else "")
            one_se.setToolTip(help_texts.COLUMN_HELP["1-SE rule"])
            cells += [NumericItem(r.get("metrics_std", {}).get(rank, float("nan"))), one_se]
            if continued:
                status = r.get("run_status", "")
                status_item = QTableWidgetItem(status)
                status_item.setToolTip(help_texts.COLUMN_HELP["Last run"])
                prev = r.get("previous_metrics")
                gain = float("nan") if prev is None else \
                    -relative_degradation(rank, prev[rank], r["metrics"][rank]) * 100 + 0.0  # no "-0.00"
                gain_item = NumericItem(gain, "{:+.2f} %")
                if gain == gain and gain > 0:
                    status_item.setBackground(QBrush(QColor(200, 240, 200)))
                    gain_item.setBackground(QBrush(QColor(200, 240, 200)))
                cells += [status_item, gain_item]
            untrained = r.get("untrained", False)
            cells += [NumericItem(r["time"], "{:.1f}") if not untrained else NumericItem(float("nan")),
                      QTableWidgetItem(r.get("reason") or str(r["config"]))]
            cells[-1].setToolTip(help_texts.NOT_TRAINED_HELP + "<br>" + r["reason"] if untrained
                                 else str(r["config"]))
            cells[0].setData(RESULT_INDEX_ROLE, row)
            for col, item in enumerate(cells):
                if row == 0 and not untrained:
                    item.setFont(bold)
                if untrained:
                    # placeholder row: greyed, not selectable (nothing to export / evaluate)
                    item.setForeground(QBrush(QColor(140, 140, 140)))
                    item.setBackground(QBrush(QColor(242, 242, 242)))
                    item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                    if col == 1:
                        item.setText(r["label"] + " - not trained")
                        item.setToolTip(help_texts.NOT_TRAINED_HELP + "<br>" + r["reason"])
                table.setItem(row, col, item)
        size_columns(table, model_column=1)
        table.setSortingEnabled(True)
        table.sortByColumn(0, Qt.AscendingOrder)  # ranking order by default
        self.update_validation_ui()
        self.update_continue_ui()
        self.update_reference_ui()

    def select_result_index(self, index):
        for row in range(self.table_results.rowCount()):
            if self.table_results.item(row, 0).data(RESULT_INDEX_ROLE) == index:
                self.table_results.selectRow(row)
                return

    def selected_results(self):
        """Selected leaderboard entries (the table may be sorted: use the stored index)."""
        if not self.automl_result:
            return []
        rows = sorted({idx.row() for idx in self.table_results.selectionModel().selectedRows()})
        indexes = [self.table_results.item(r, 0).data(RESULT_INDEX_ROLE) for r in rows]
        entries = [self.automl_result["results"][i] for i in indexes if i is not None]
        return [e for e in entries if not e.get("untrained")]  # placeholder rows have no model

    def on_selection_changed(self):
        """Selecting rows only chooses the models to export: no training here."""
        selected = self.selected_results()
        self.button_export.setEnabled(bool(selected) and not self.fit_running())
        self.Outputs.learner.send(selected[0]["learner"] if selected else None)

    def fit_running(self):
        return self.fit_thread is not None and self.fit_thread.isRunning()

    def train_on_all_then(self, entries, on_done, message):
        """Train the entries on all data in a thread (if not already done), then call on_done."""
        missing = [e for e in entries if e["model"] is None]
        if not missing:
            on_done()
            return
        if self.fit_running():
            self.pending_fit = (entries, on_done, message)
            return
        self.button_export.setEnabled(False)
        run_id = self.run_id
        self.label_status.setText(message)
        self.progressBarInit()
        self.fit_thread = thread_management.Thread(automl_functions.train_entries_on_all, missing, self.data)
        self.fit_thread.progress.connect(lambda v, rid=run_id: rid == self.run_id and self.progressBarSet(v))
        self.fit_thread.result.connect(lambda _r, rid=run_id: rid == self.run_id and on_done())
        self.fit_thread.error.connect(lambda e, rid=run_id: rid == self.run_id and self.handle_error(e))
        self.fit_thread.finish.connect(self.handle_fit_finish)
        self.fit_thread.start()

    def handle_fit_finish(self):
        self.progressBarFinished()
        self.button_export.setEnabled(bool(self.selected_results()))
        self.update_validation_ui()
        if self.pending_fit is not None:
            entries, on_done, message = self.pending_fit
            self.pending_fit = None
            QTimer.singleShot(0, lambda: self.train_on_all_then(entries, on_done, message))

    # ------------------------------------------------------------------ Export
    def browse_folder(self, parent=None):
        folder = QFileDialog.getExistingDirectory(parent or self, "Folder where to export the models",
                                                  self.export_folder or os.path.expanduser("~"))
        if folder:
            self.export_folder = folder
            self.line_folder.setText(folder)
            if self.validation_dialog is not None:
                self.validation_dialog.line_folder.setText(folder)
        return bool(folder)

    @staticmethod
    def model_file_path(entry, folder):
        filename = re.sub(r'[^\w.-]+', "_", entry["label"].replace("[frozen]", "reference")).strip("_")
        return os.path.join(folder, f"automl_{filename}.pkcls")

    def confirm_overwrite(self, entries, folder, parent=None):
        """
        Ask before overwriting existing files.
        Returns the list of (entry, path) to write, or None if the export is cancelled.
        """
        to_write, overwrite_all = [], False
        for entry in entries:
            path = self.model_file_path(entry, folder)
            if os.path.exists(path) and not overwrite_all:
                answer = QMessageBox.question(
                    parent or self, "File already exists",
                    f"The file\n{path}\nalready exists.\n\nDo you want to replace it?",
                    QMessageBox.Yes | QMessageBox.YesToAll | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.No)
                if answer == QMessageBox.Cancel:
                    return None
                if answer == QMessageBox.No:
                    continue
                if answer == QMessageBox.YesToAll:
                    overwrite_all = True
            to_write.append((entry, path))
        return to_write

    def export_selected_models(self):
        """Export the models selected in the main table."""
        self.export_entries(self.selected_results())

    def export_entries(self, selected, parent=None):
        """
        Re-train the models on ALL the training data (never on the validation data), save them
        and send the first one on 'Model'. `parent`: window in front of which the dialogs open.
        """
        self.error("")
        if not selected:
            return
        if self.fit_running():
            QMessageBox.information(parent or self, "AutoML export",
                                    "A training is in progress, please wait for it to finish.")
            return
        folder = self.export_folder
        if not folder or not os.path.isdir(folder):
            if not self.browse_folder(parent):
                return
            folder = self.export_folder
        to_write = self.confirm_overwrite(selected, folder, parent)
        if to_write is None:
            self.label_status.setText("Export cancelled.")
            return
        self.train_on_all_then(selected, lambda: self.finish_export(selected, to_write, folder, parent),
                               f"Training {len(selected)} model(s) on all {len(self.data)} rows...")

    def finish_export(self, selected, to_write, folder, parent=None):
        saved, errors = [], []
        for entry, path in to_write:
            try:
                with open(path, "wb") as f:
                    pickle.dump(entry["model"], f, protocol=pickle.HIGHEST_PROTOCOL)
                saved.append(path)
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")

        # the first selected model, trained on all data, goes to the "Model" output
        self.Outputs.model.send(selected[0]["model"])

        skipped = len(to_write) < len(selected)
        msg = (f"{len(saved)} model(s) trained on all the {len(self.data)} training rows "
               f"(validation data never used) and saved in:\n{folder}\n\n")
        msg += "\n".join(os.path.basename(p) for p in saved)
        if skipped:
            msg += f"\n\n{len(selected) - len(to_write)} model(s) not saved (existing file kept)."
        msg += f"\n\n'Model' output: {selected[0]['label']}\n(load the files with the 'Load Model' widget)"
        self.label_status.setText(f"{len(saved)} model(s) exported to {folder}. "
                                  f"'Model' output: {selected[0]['label']}.")
        if errors:
            self.error("Export errors: " + "; ".join(errors))
            QMessageBox.warning(parent or self, "AutoML export", msg + "\n\nErrors:\n" + "\n".join(errors))
        else:
            QMessageBox.information(parent or self, "AutoML export", msg)

    # ------------------------------------------------------------------ Validation
    def update_validation_ui(self):
        if self.validation_data is None:
            self.label_validation.setText('No validation data (connect a table on the "Validation Data" input).')
        else:
            self.label_validation.setText(
                f"Validation data: {len(self.validation_data)} rows (never used by the search "
                f"nor the cross-validation).")
        self.button_validate.setEnabled(bool(self.automl_result) and self.validation_data is not None
                                        and not self.fit_running())

    def evaluate_on_validation(self):
        """Re-train every model on all the training data and score it on the validation data."""
        if not self.automl_result or self.validation_data is None or self.fit_running():
            return
        self.error("")
        entries = automl_functions.trained_results(self.automl_result)
        run_id = self.run_id
        self.button_validate.setEnabled(False)
        self.button_export.setEnabled(False)
        self.label_status.setText(f"Validation: training {len(entries)} models on all "
                                  f"{len(self.data)} rows and scoring them...")
        self.progressBarInit()
        self.fit_thread = thread_management.Thread(
            automl_functions.evaluate_on_validation, entries, self.data, self.validation_data,
            bool(self.automl_result["is_classification"]))
        self.fit_thread.progress.connect(lambda v, rid=run_id: rid == self.run_id and self.progressBarSet(v))
        self.fit_thread.result.connect(lambda r, rid=run_id: rid == self.run_id and self.show_validation(r))
        self.fit_thread.error.connect(lambda e, rid=run_id: rid == self.run_id and self.handle_error(e))
        self.fit_thread.finish.connect(self.handle_fit_finish)
        self.fit_thread.start()

    def show_validation(self, validation):
        self.label_status.setText(f"Validation done on {validation['n_used']} rows.")
        if self.validation_dialog is not None:
            self.validation_dialog.close()
        self.validation_dialog = ValidationDialog(self, validation)
        self.validation_dialog.show()
        self.validation_dialog.raise_()

    def onDeleteWidget(self):
        if self.validation_dialog is not None:
            self.validation_dialog.close()
        self.cancel_running()
        super().onDeleteWidget()

    def post_initialized(self):
        """Hook for apply_modification_from_python_file."""
        pass


if __name__ == "__main__":
    from orangewidget.utils.widgetpreview import WidgetPreview
    WidgetPreview(OWAutoML).run(Orange.data.Table("iris"))
