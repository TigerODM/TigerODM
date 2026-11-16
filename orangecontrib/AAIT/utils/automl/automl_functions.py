"""
AutoML functions based on FLAML (CPU only).

Main entry point: `run_automl(data, ...)`
    1. detects the task from the target (Discrete -> classification, Continuous -> regression)
    2. FLAML searches the best algorithm / hyper-parameters (5-fold cross-validation)
    3. each best configuration (+ an optional stacking ensemble) is evaluated by an
       Orange 5-fold cross-validation: accuracy / F1 / AUC or RMSE / MAE / R²
    4. each model is re-trained on the whole data and returned as an Orange Model
"""
import os
import threading
import time

import numpy as np
from Orange.data import Table, Domain, ContinuousVariable, StringVariable

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.automl.orange_automl import (
        FlamlLearner, DEFAULT_PREPROCESSORS, sanitize_config, make_meta_model, CUSTOM_ESTIMATORS,
        FrozenLearner, reference_template, describe_template, UnsupportedReferenceModel, estimator_label,
        N_SPLITS, SEED)
else:
    from orangecontrib.AAIT.utils.automl.orange_automl import (
        FlamlLearner, DEFAULT_PREPROCESSORS, sanitize_config, make_meta_model, CUSTOM_ESTIMATORS,
        FrozenLearner, reference_template, describe_template, UnsupportedReferenceModel, estimator_label,
        N_SPLITS, SEED)


SEARCH_SHARE = 0.8  # part of the time out given to the FLAML search, the rest is for the cross-validation

CLASSIFICATION_ESTIMATORS = ["lgbm", "xgboost", "xgb_limitdepth", "xgb_rf", "histgb", "rf", "extra_tree", "catboost",
                             "lrl1", "lrl2_scaled", "sgd_scaled", "sgd_raw", "knn_scaled"]
REGRESSION_ESTIMATORS = ["lgbm", "xgboost", "xgb_limitdepth", "xgb_rf", "histgb", "rf", "extra_tree", "catboost",
                         "enet_scaled", "sgd_scaled", "sgd_raw", "knn_scaled"]
DEFAULT_UNCHECKED = ["catboost"]  # slow, and writes a catboost_info folder

WEIGHTED_F1 = "weighted_f1 (ODM F1)"
CLASSIFICATION_METRICS = ["macro_f1", WEIGHTED_F1, "accuracy", "roc_auc", "log_loss"]
REGRESSION_METRICS = ["rmse", "r2", "mae"]

# metric used to rank the leaderboard: (name, higher_is_better)
# classification ranking: Orange's F1 (weighted average, as Test & Score)
RANKING_METRIC = {True: ("Weighted F1", True), False: ("RMSE", False)}


class AutoMLStopped(Exception):
    pass


def get_task_info(data):
    """
    Returns (is_classification, error_message).
    is_classification is None if the target is not usable.
    """
    if data is None:
        return None, "No data."
    class_vars = data.domain.class_vars
    if len(class_vars) == 0:
        return None, "The data has no target variable (set one with 'Select Columns')."
    if len(class_vars) > 1:
        return None, "Only one target variable is supported."
    target = class_vars[0]
    if target.is_discrete:
        if len(target.values) < 2:
            return None, "The categorical target must have at least 2 values."
        return True, ""
    if target.is_continuous:
        return False, ""
    return None, "The target must be categorical (classification) or numeric (regression)."


def available_estimators(is_classification):
    names = CLASSIFICATION_ESTIMATORS if is_classification else REGRESSION_ESTIMATORS
    result = []
    for name in names:
        if name == "lgbm" and not _module_exists("lightgbm"):
            continue
        if name.startswith("xgb") and not _module_exists("xgboost"):
            continue
        if name == "catboost" and not _module_exists("catboost"):
            continue
        result.append(name)
    return result


def _module_exists(name):
    import importlib.util
    return importlib.util.find_spec(name) is not None


def preprocess(data):
    for pp in DEFAULT_PREPROCESSORS:
        data = pp(data)
    return data


def compute_metrics(is_classification, y_true, y_pred, probs=None, folds=None):
    """
    Same computation as Orange's Test & Score with "(None, show average over classes)":
    - Accuracy, "Weighted F1" / Precision / Recall averaged over the classes WEIGHTED by
      their number of rows (sklearn average="weighted"), on all the predictions;
    - "F1" (macro average, not in Test & Score): F1 with the same weight for every class;
    - AUC computed on each fold then averaged over the folds (`folds`: list of slices or
      index arrays; None = a single block, e.g. validation data), see `orange_auc`.
    """
    from sklearn import metrics
    if is_classification:
        y_true = y_true.astype(int)
        y_pred = y_pred.astype(int)
        res = {
            "Accuracy": metrics.accuracy_score(y_true, y_pred),
            "Weighted F1": metrics.f1_score(y_true, y_pred, average="weighted", zero_division=0),
            "F1": metrics.f1_score(y_true, y_pred, average="macro", zero_division=0),
            "Precision": metrics.precision_score(y_true, y_pred, average="weighted", zero_division=0),
            "Recall": metrics.recall_score(y_true, y_pred, average="weighted", zero_division=0),
            "AUC": np.nan,
        }
        if probs is not None:
            res["AUC"] = orange_auc(y_true, probs, folds)
        return res
    mse = metrics.mean_squared_error(y_true, y_pred)
    return {
        "RMSE": float(np.sqrt(mse)),
        "MAE": metrics.mean_absolute_error(y_true, y_pred),
        "R2": metrics.r2_score(y_true, y_pred),
    }


def _auc_one_block(y, probs):
    """Orange's AUC on one block: binary -> class 1; multiclass -> one-vs-rest AUC of each
    class present, weighted by c * (N - c) (c = rows of the class), as Orange.evaluation.AUC."""
    from sklearn import metrics
    if probs.shape[1] == 2:
        return metrics.roc_auc_score(y == 1, probs[:, 1])
    classes = np.unique(y)
    counts = np.array([np.sum(y == c) for c in classes], dtype=float)
    weights = counts * (len(y) - counts)
    if weights.sum() == 0:
        raise ValueError("only one class")
    aucs = np.array([metrics.roc_auc_score(y == c, probs[:, int(c)]) for c in classes])
    return float(np.sum(aucs * weights / weights.sum()))


def orange_auc(y, probs, folds=None):
    """AUC as in Orange's Test & Score: computed per fold, then averaged over the folds."""
    blocks = [slice(None)] if not folds else list(folds)
    scores = []
    for block in blocks:
        try:
            scores.append(_auc_one_block(y[block], probs[block]))
        except ValueError:  # a single class in this block
            continue
    return float(np.mean(scores)) if scores else np.nan


def cross_validate(learner, data, is_classification, n_splits=N_SPLITS, callback=None):
    """
    Orange k-fold cross-validation of one learner (same folds for every learner: fixed seed).
    Returns (Orange Results, metrics dict).
    """
    from Orange.evaluation import CrossValidation
    cv = CrossValidation(k=n_splits, stratified=is_classification, random_state=SEED, store_data=True)
    res = cv(data, [learner], callback=callback)
    if res.failed is not None and res.failed[0]:
        raise ValueError(str(res.failed[0]))
    probs = res.probabilities[0] if is_classification else None
    return res, compute_metrics(is_classification, res.actual, res.predicted[0], probs, folds=res.folds)


def merge_results(results_list, names):
    """
    Merge single-learner cross-validation Results (same folds) into one Results,
    like the 'Evaluation Results' output of Test & Score.
    """
    from Orange.evaluation import Results
    first = results_list[0]
    for r in results_list[1:]:
        if not np.array_equal(r.row_indices, first.row_indices):
            raise ValueError("Cross-validation folds differ between models.")
    merged = Results(
        data=first.data, domain=first.domain,
        row_indices=first.row_indices, folds=first.folds, actual=first.actual,
        predicted=np.vstack([r.predicted for r in results_list]),
        probabilities=(np.vstack([r.probabilities for r in results_list])
                       if first.probabilities is not None and first.probabilities.size else None),
        learners=[r.learners[0] for r in results_list],
        failed=[False] * len(results_list),
    )
    merged.learner_names = list(names)
    return merged


def voting_cv_results(members_results, learner, is_classification):
    """
    Cross-validated predictions of a voting ensemble, computed from its members' ones.
    With the same folds, a voting ensemble trained on a fold predicts exactly the mean of
    its members trained on that fold: no extra training is needed.
    """
    import copy
    res = copy.copy(members_results[0])
    if is_classification:
        probs = np.mean([r.probabilities[0] for r in members_results], axis=0)
        res.probabilities = probs[None, :, :]
        res.predicted = np.argmax(probs, axis=1).astype(float)[None, :]
    else:
        res.probabilities = members_results[0].probabilities
        res.predicted = np.mean([r.predicted[0] for r in members_results], axis=0)[None, :]
    res.learners = [learner]
    res.models = None
    res.failed = [False]
    probs = res.probabilities[0] if is_classification else None
    return res, compute_metrics(is_classification, res.actual, res.predicted[0], probs, folds=res.folds)


def stacking_cv_results(members_results, learner, is_classification):
    """
    Cross-validated predictions of a stacking ensemble, without re-training the members.

    The members' cross-validated predictions ("level-one data") are the meta-model's
    features, as in the stacking itself. For each fold, the meta-model is trained on the
    level-one data of the other folds and predicts this fold (same folds as the members).
    """
    import copy
    first = members_results[0]
    n = len(first.actual)
    if is_classification:
        n_classes = first.probabilities.shape[2]
        # same features as sklearn's StackingClassifier: probabilities, first column dropped if binary
        blocks = [r.probabilities[0][:, 1:] if n_classes == 2 else r.probabilities[0] for r in members_results]
    else:
        blocks = [r.predicted[0][:, None] for r in members_results]
    Z = np.hstack(blocks)
    y = first.actual.astype(int) if is_classification else first.actual

    predicted = np.zeros(n)
    probs = np.zeros((n, n_classes)) if is_classification else None
    for fold in first.folds:
        test = np.zeros(n, dtype=bool)
        test[fold] = True
        meta = make_meta_model(is_classification)
        meta.fit(Z[~test], y[~test])
        if is_classification:
            p = np.zeros((test.sum(), n_classes))
            p[:, meta.classes_.astype(int)] = meta.predict_proba(Z[test])
            probs[test] = p
            predicted[test] = np.argmax(p, axis=1)
        else:
            predicted[test] = meta.predict(Z[test])

    res = copy.copy(first)
    res.predicted = predicted[None, :]
    res.probabilities = probs[None, :, :] if is_classification else first.probabilities
    res.learners = [learner]
    res.models = None
    res.failed = [False]
    return res, compute_metrics(is_classification, res.actual, predicted, probs, folds=first.folds)


def cv_fold_std(cv_results, is_classification):
    """Standard deviation of each metric across the cross-validation folds."""
    per_fold = []
    probs_all = cv_results.probabilities[0] if is_classification else None
    for fold in cv_results.folds:
        probs = probs_all[fold] if is_classification else None
        try:
            per_fold.append(compute_metrics(is_classification, cv_results.actual[fold],
                                            cv_results.predicted[0][fold], probs))
        except ValueError:
            continue
    if len(per_fold) < 2:
        return {}
    return {k: float(np.nanstd([f[k] for f in per_fold], ddof=1)) for k in per_fold[0]}


# Complexity order used by the 1-SE rule to prefer the simplest model (lower = simpler)
COMPLEXITY = {
    "lrl1": 1, "lrl2_scaled": 1, "enet_scaled": 1, "sgd_scaled": 1, "sgd_raw": 1,
    "knn_scaled": 2,
    "rf": 3, "extra_tree": 3, "xgb_rf": 3,
    "histgb": 4, "lgbm": 4, "xgboost": 4, "xgb_limitdepth": 4, "catboost": 4,
    "reference": 4,
    "ensemble": 5,
    "stacking": 6,
}


def apply_one_se_rule(results, rank_name, higher_better, n_splits=N_SPLITS):
    """
    "One standard error" rule (Breiman et al.): every model whose CV score is within one
    standard error (fold std / sqrt(k)) of the best one is statistically as good; among
    them, recommend the simplest one (it generalises more safely), then the best score.
    Sets r["within_1se"] and r["one_se_pick"]; returns a summary dict.
    """
    best = results[0]
    std = best.get("metrics_std", {}).get(rank_name, np.nan)
    se = std / np.sqrt(n_splits) if std == std else 0.0
    best_score = best["metrics"][rank_name]
    threshold = best_score - se if higher_better else best_score + se
    for r in results:
        s = r["metrics"][rank_name]
        r["within_1se"] = bool(s >= threshold if higher_better else s <= threshold)
        r["one_se_pick"] = False
    candidates = [r for r in results if r["within_1se"]]
    pick = min(candidates, key=lambda r: (COMPLEXITY.get(r["name"], 4),
                                          -r["metrics"][rank_name] if higher_better else r["metrics"][rank_name]))
    pick["one_se_pick"] = True
    return {"label": pick["label"], "standard_error": float(se), "threshold": float(threshold),
            "n_within": len(candidates), "metric": rank_name}


def predictions_table(automl_result):
    """Data + cross-validated predictions (+ probabilities and fold), like Test & Score 'Predictions'."""
    res = automl_result["evaluation_results"]
    return res.get_augmented_data(res.learner_names)


def train_on_all(result_entry, data):
    """Train the model of a leaderboard entry on the whole data (used for the Model output and export)."""
    if result_entry.get("model") is None:
        model = result_entry["learner"](data)
        model.name = result_entry["label"]
        result_entry["model"] = model
    return result_entry["model"]


def model_metrics(model, data, is_classification):
    """
    Metrics of a trained Orange model on `data`. Returns (metrics, n_rows_used, n_unknown_class).

    Orange's Model.__call__ maps the predictions (values and probabilities) back to the
    target variable of `data`, so `data` may have been loaded separately, with its class
    values in another order: its own target column is the ground truth.
    Rows of a class unknown to the model stay in the metrics (they are real errors).
    """
    data = data[np.flatnonzero(np.isfinite(np.asarray(data.get_column(data.domain.class_var), dtype=float)))]
    if len(data) == 0:
        raise ValueError("No row with a known target value.")
    y = np.asarray(data.get_column(data.domain.class_var), dtype=float)
    if is_classification:
        known = set(model.domain.class_var.values)
        n_unknown = int(sum(data.domain.class_var.values[int(v)] not in known for v in y))
        values, probs = model(data, model.ValueProbs)
        values = np.asarray(values, dtype=float)
        return compute_metrics(True, y, values, probs), len(data), n_unknown, (y, values, probs)
    values = np.asarray(model(data), dtype=float)
    return compute_metrics(False, y, values), len(data), 0, (y, values, None)


N_BOOTSTRAP = 500
N_BOOTSTRAP_AUC = 100  # AUC is much slower to compute


def _fast_classification(y, pred, n_classes):
    """Accuracy and WEIGHTED Precision / Recall / F1 (sklearn average="weighted", zero_division=0)."""
    precision, recall, f1, support, present = [], [], [], [], []
    for c in range(n_classes):
        t, p = y == c, pred == c
        tp, n_true, n_pred = np.sum(t & p), np.sum(t), np.sum(p)
        support.append(n_true)
        present.append(n_true + n_pred > 0)  # sklearn macro: labels present in y or pred
        precision.append(tp / n_pred if n_pred else 0.0)
        recall.append(tp / n_true if n_true else 0.0)
        f1.append(2 * tp / (n_true + n_pred) if n_true + n_pred else 0.0)
    w = np.array(support, dtype=float)
    w = w / w.sum() if w.sum() else w
    return {"Accuracy": np.mean(y == pred), "Weighted F1": float(np.sum(np.array(f1) * w)),
            "F1": float(np.mean(np.array(f1)[np.array(present)])),
            "Precision": float(np.sum(np.array(precision) * w)), "Recall": float(np.sum(np.array(recall) * w))}


def _fast_regression(y, pred):
    err = pred - y
    ss_tot = np.sum((y - y.mean()) ** 2)
    return {"RMSE": np.sqrt(np.mean(err ** 2)), "MAE": np.mean(np.abs(err)),
            "R2": 1 - np.sum(err ** 2) / ss_tot if ss_tot > 0 else np.nan}


def bootstrap_ci(is_classification, y, pred, probs=None, level=0.95, seed=SEED):
    """
    Percentile bootstrap confidence interval of each metric: the validation rows are
    resampled with replacement and the metric recomputed; the interval contains the
    central `level` part of these values. Returns {metric: (low, high)}.
    """
    rng = np.random.RandomState(seed)
    n = len(y)
    samples = {}
    yi = y.astype(int) if is_classification else y
    pi = pred.astype(int) if is_classification else pred
    n_classes = probs.shape[1] if probs is not None else int(max(yi.max(), pi.max()) + 1) if is_classification else 0
    for b in range(N_BOOTSTRAP):
        idx = rng.randint(0, n, n)
        m = _fast_classification(yi[idx], pi[idx], n_classes) if is_classification \
            else _fast_regression(y[idx], pred[idx])
        if is_classification and probs is not None and b < N_BOOTSTRAP_AUC:
            m["AUC"] = compute_metrics(True, y[idx], pred[idx], probs[idx])["AUC"]
        for k, v in m.items():
            samples.setdefault(k, []).append(v)
    alpha = (1 - level) / 2
    return {k: (float(np.nanpercentile(v, 100 * alpha)), float(np.nanpercentile(v, 100 * (1 - alpha))))
            if np.isfinite(v).any() else (np.nan, np.nan) for k, v in samples.items()}


def evaluate_on_validation(entries, train_data, validation_data, is_classification, progress_callback=None):
    """
    Hold-out evaluation: each model is re-trained on ALL the training data (as for the
    export), then scored on the training data itself and on the validation data, which
    was never used before (neither by the search nor by the cross-validation).
    """
    target_name = train_data.domain.class_var.name
    vclass = validation_data.domain.class_var
    if vclass is None or vclass.name != target_name:
        raise ValueError(f"The validation data must have the same target variable '{target_name}'.")
    if vclass.is_discrete != is_classification:
        raise ValueError(f"The target '{target_name}' must have the same type in both data.")
    validation_names = {v.name for v in validation_data.domain.variables + validation_data.domain.metas}
    missing = [a.name for a in train_data.domain.attributes if a.name not in validation_names]
    overlap = 0
    if getattr(train_data, "ids", None) is not None and getattr(validation_data, "ids", None) is not None:
        overlap = int(np.isin(validation_data.ids, train_data.ids).sum())

    rows = []
    n_used, n_unknown = 0, 0
    for i, entry in enumerate(entries):
        model = train_on_all(entry, train_data)
        train_metrics, _, _, _ = model_metrics(model, train_data, is_classification)
        val_metrics, n_used, n_unknown, (y, pred, probs) = model_metrics(model, validation_data, is_classification)
        rows.append({"entry": entry, "label": entry["label"], "train": train_metrics,
                     "cv": entry["metrics"], "cv_std": entry.get("metrics_std", {}),
                     "one_se_pick": entry.get("one_se_pick", False),
                     "validation": val_metrics,
                     "validation_ci": bootstrap_ci(is_classification, y, pred, probs)})
        if progress_callback is not None:
            progress_callback(100.0 * (i + 1) / len(entries))
    return {"rows": rows, "is_classification": is_classification,
            "n_train": len(train_data), "n_validation": len(validation_data), "n_used": n_used,
            "n_unknown_class": n_unknown, "missing_features": missing, "overlap": overlap}


def train_entries_on_all(entries, data, progress_callback=None):
    for i, entry in enumerate(entries):
        train_on_all(entry, data)
        if progress_callback is not None:
            progress_callback(100.0 * (i + 1) / len(entries))
    return entries


def weighted_f1_loss(X_val, y_val, estimator, labels, X_train, y_train, *args, **kwargs):
    """
    FLAML custom metric: 1 - F1 weighted by the number of rows of each class, i.e. the F1
    shown by Orange's Test & Score (and by this widget). FLAML minimises the returned loss.
    """
    from sklearn.metrics import f1_score
    score = f1_score(y_val, estimator.predict(X_val), average="weighted", zero_division=0)
    return 1.0 - score, {"weighted_f1": score}


def _flaml_metric(metric, is_classification, n_classes):
    if metric in (None, "", "auto"):
        return "macro_f1" if is_classification else "rmse"
    if metric == WEIGHTED_F1:
        return weighted_f1_loss
    if metric == "roc_auc" and n_classes > 2:
        return "roc_auc_ovr"
    return metric


def run_automl(data, time_budget=60, n_jobs=1, estimator_list=None, metric="auto",
               ensemble=True, stacking=True, progress_callback=None, argself=None, previous=None,
               reference_model=None, zero_shot=False):
    """
    Run FLAML AutoML on an Orange Table.

    `zero_shot`: start the search of the algorithms covered by FLAML's pre-learned portfolio
    (LightGBM, Random Forest, Extra Trees, XGBoost) from the configuration it suggests for
    data of this shape, instead of a minimal configuration (not used for an algorithm that
    continues from its own previous best configuration).
    `reference_model`: optional Orange model (e.g. from "Load Model") whose architecture is
    FROZEN: same estimator and hyper-parameters (not tuned), re-trained and cross-validated on
    the current data, and compared with the FLAML models (not used in the ensembles).

    `previous`: result of a previous run on the SAME data, to continue the search
    ("warm start"): only the algorithms of `estimator_list` are searched again, starting
    from their best configuration; the other models of `previous` are kept unchanged.

    :return: dict with keys
        task, is_classification, target, metric, ranking_metric, results, best_index, search_time
        results: list of dict(name, label, config, flaml_loss, metrics, model, learner)
                 sorted from best to worst; `model` is an Orange Model trained on all data.
    """
    def progress(value):
        if progress_callback is not None:
            progress_callback(float(value))

    def check_stop():
        if argself is not None and getattr(argself, "stop", False):
            raise AutoMLStopped()

    is_classification, msg = get_task_info(data)
    if is_classification is None:
        raise ValueError(msg)
    target = data.domain.class_var
    n_classes = len(target.values) if is_classification else 0
    # rows without target can be neither learned nor evaluated (same as Test & Score)
    from Orange.data.filter import HasClass
    data = HasClass()(data)

    pdata = preprocess(data)
    if len(pdata) < N_SPLITS * 2:
        raise ValueError(f"Not enough rows with a defined target ({len(pdata)}).")
    if len(pdata.domain.attributes) == 0:
        raise ValueError("No usable feature (all attributes are text/meta?).")

    X = np.asarray(pdata.X, dtype=float)
    y = pdata.Y.ravel()
    if is_classification:
        y = y.astype(int)
        counts = np.bincount(y)
        if (counts[counts > 0] < N_SPLITS).any():
            raise ValueError(f"Each class must have at least {N_SPLITS} rows for a {N_SPLITS}-fold cross-validation.")

    available = available_estimators(is_classification)
    if estimator_list:
        estimator_list = [e for e in estimator_list if e in available]
    else:
        estimator_list = [e for e in available if e not in DEFAULT_UNCHECKED]
    if not estimator_list:
        raise ValueError("No algorithm selected.")

    flaml_metric = _flaml_metric(metric, is_classification, n_classes)
    if previous is not None:
        if previous["is_classification"] != is_classification:
            raise ValueError("The task changed since the previous run: start a new run.")
        # same optimisation metric, otherwise the FLAML losses are not comparable
        flaml_metric = previous["metric"]

    progress(0)
    # FLAML's tuner keeps its state in module globals: two searches running at the same time
    # (e.g. a cancelled run still finishing while a new one starts, or two AutoML widgets)
    # corrupt each other (StopIteration, "unexpected keyword argument 'C'"...).
    # -> only one search at a time; a cancelled search is stopped after its current trial.
    try:
        while not _FLAML_LOCK.acquire(timeout=0.2):
            check_stop()
        try:
            return _run_search(data, is_classification, target, X, y, estimator_list, flaml_metric,
                               time_budget, n_jobs, ensemble, stacking, progress, check_stop, argself,
                               previous, reference_model, zero_shot)
        finally:
            _FLAML_LOCK.release()
    except AutoMLStopped:
        # cancelled by the widget (new data / new run / widget closed): not an error,
        # the widget ignores the result of a cancelled run
        print("AutoML: run cancelled.")
        return None


_FLAML_LOCK = threading.Lock()


def _stop_flaml(automl):
    """Ask a running FLAML search to stop after its current trial."""
    state = getattr(automl, "_state", None)
    if state is not None:
        state.time_budget = 0


def zero_shot_starting_points(names, X, y, is_classification):
    """
    FLAML "zero-shot" configurations: for each algorithm covered by FLAML's portfolio
    (meta-learned on hundreds of public datasets), the configuration suggested for data of
    this shape. Algorithms outside the portfolio are simply not in the result.
    Everything is local: the portfolio is installed with FLAML.
    """
    from flaml.default import suggest_config
    from flaml.automl.task.factory import task_factory
    task = task_factory("classification" if is_classification else "regression", X, y)
    points = {}
    for name in names:
        try:
            configs = suggest_config(task, X, y, name, "", k=1)
            space = task.estimator_class_from_str(name).search_space(data_size=X.shape, task=task)
        except Exception:  # not in the portfolio (FileNotFoundError) or other issue
            continue
        if configs:
            config = _clip_to_space(configs[0]["hyperparameters"], space)
            if config:
                points[name] = config
    return points


def _clip_to_space(config, space):
    """
    Bring a configuration inside the search space. The portfolio was learned on larger
    datasets: on small data its numbers of trees / leaves exceed the bounds FLAML derives
    from the number of rows, and FLAML would then silently DROP the whole starting point.
    Numeric values are clipped to [lower, upper]; invalid categorical values are removed.
    """
    clipped = {}
    for key, value in config.items():
        domain = space.get(key, {}).get("domain")
        if domain is None:
            continue
        lower, upper = getattr(domain, "lower", None), getattr(domain, "upper", None)
        if lower is not None and upper is not None and isinstance(value, (int, float)):
            if isinstance(lower, int) and isinstance(upper, int):
                # flaml integer domains exclude the upper bound
                value = int(min(max(int(round(value)), lower), upper - 1))
            else:
                value = float(min(max(value, lower), upper))
            clipped[key] = value
        elif not hasattr(domain, "sample") or getattr(domain, "categories", None) is None \
                or value in domain.categories:
            clipped[key] = value
    return clipped


def _filter_starting_points(starting_points, learner_classes, X, y, is_classification, custom_hp):
    """
    Keep, in each warm-start configuration, only the hyper-parameters of the estimator's
    search space: a best configuration may contain other keys (e.g. "max_iter" for SGD),
    which make FLAML crash (KeyError) when given as a starting point.
    An estimator whose search space cannot be computed simply starts without starting point.
    """
    if not starting_points:
        return {}
    from flaml.automl.task.factory import task_factory
    task = task_factory("classification" if is_classification else "regression", X, y)
    filtered = {}
    for name, config in starting_points.items():
        try:
            space = dict(learner_classes[name].search_space(data_size=X.shape, task=task))
            space.update((custom_hp or {}).get(name, {}))
        except Exception as e:
            print(f"AutoML: no warm start for {name} ({e})")
            continue
        config = {k: v for k, v in config.items() if k in space}
        if config:
            filtered[name] = config
    return filtered


def reference_label(model):
    name = getattr(model, "name", None) or type(model).__name__
    return f"[frozen] {name}"


def check_reference_model(model, data):
    """Returns an error message if `model` cannot be used as reference for `data`, else ""."""
    if model is None or data is None or data.domain.class_var is None:
        return ""
    model_class = getattr(getattr(model, "domain", None), "class_var", None)
    if model_class is None:
        return "The reference model has no target variable."
    if model_class.is_discrete != data.domain.class_var.is_discrete:
        kind = "classification" if model_class.is_discrete else "regression"
        return (f"The reference model is a {kind} model, not compatible with the target "
                f"'{data.domain.class_var.name}'.")
    try:
        reference_template(model)
    except UnsupportedReferenceModel as e:
        return str(e)
    return ""


def _reference_entry(reference_model, previous, data, is_classification, skipped, check_stop):
    """Leaderboard entry of the frozen reference model (re-used if unchanged since `previous`)."""
    if reference_model is None:
        return None
    prev = None if previous is None else next(
        (r for r in previous["results"] if r["name"] == "reference"), None)
    if prev is not None and prev.get("reference_model") is reference_model:
        prev["run_status"] = "frozen"
        prev["previous_metrics"] = prev["metrics"]
        return prev
    message = check_reference_model(reference_model, data)
    if message:
        skipped.append(f"reference model ({message})")
        return None
    template = reference_template(reference_model)
    learner = FrozenLearner(template, is_classification, reference_label(reference_model))
    check_stop()
    t0 = time.time()
    try:
        cv_results, metrics = cross_validate(learner, data, is_classification)
    except Exception as e:
        skipped.append(f"{learner.name} (error: {e})")
        return None
    return {
        "name": "reference",
        "label": learner.name,
        "config": describe_template(template),
        "flaml_loss": np.nan,
        "metrics": metrics,
        "time": time.time() - t0,
        "cv_results": cv_results,
        "model": None,
        "learner": learner,
        "run_status": "frozen",
        "previous_metrics": None if prev is None else prev["metrics"],
        "reference_model": reference_model,
        "frozen": True,
    }


def _run_search(data, is_classification, target, X, y, estimator_list, flaml_metric,
                time_budget, n_jobs, ensemble, stacking, progress, check_stop, argself, previous=None,
                reference_model=None, zero_shot=False):
    from flaml import AutoML

    # previous single models (not the ensembles, which are rebuilt), by algorithm
    previous_singles = {} if previous is None else {
        r["name"]: r for r in previous["results"]
        if r["name"] not in ("ensemble", "stacking", "reference") and not r.get("untrained")}
    previous_ensembles = {} if previous is None else {
        r["name"]: r for r in previous["results"] if r["name"] in ("ensemble", "stacking")}
    # warm start: the searched algorithms restart from their best known configuration
    starting_points = {name: dict(previous_singles[name]["config"])
                       for name in estimator_list if name in previous_singles}

    # The time out covers the whole processing: FLAML gets SEARCH_SHARE of it, the rest is
    # kept for the cross-validation of the best configurations.
    start = time.time()
    deadline = start + time_budget
    search_budget = max(1.0, time_budget * SEARCH_SHARE)

    # --- 1. FLAML search (progress 0 -> 80%) --------------------------------
    automl = AutoML()
    done = threading.Event()

    def ticker():
        while not done.wait(0.5):
            progress(min(80.0, 80.0 * (time.time() - start) / search_budget))
            if argself is not None and getattr(argself, "stop", False):
                _stop_flaml(automl)
    threading.Thread(target=ticker, daemon=True).start()

    custom_hp = {}
    if "catboost" in estimator_list:
        # FLAML's first CatBoost trial uses 8192 trees and cannot be interrupted by the
        # time budget (> 60 s on iris): bound the number of trees.
        from flaml import tune
        custom_hp["catboost"] = {"n_estimators": {"domain": tune.lograndint(10, 1000),
                                                  "init_value": 100, "low_cost_init_value": 10}}

    for custom_name, custom_class in CUSTOM_ESTIMATORS.items():
        if custom_name in estimator_list:
            automl.add_learner(custom_name, custom_class)
    starting_points = _filter_starting_points(
        starting_points, {name: r["learner"].estimators[0][1] for name, r in previous_singles.items()},
        X, y, is_classification, custom_hp)
    zero_shot_points = {}
    if zero_shot:
        # algorithms without a previous best configuration start from FLAML's portfolio
        zero_shot_points = zero_shot_starting_points(
            [n for n in estimator_list if n not in starting_points], X, y, is_classification)
        starting_points.update(zero_shot_points)
    try:
        automl.fit(
            custom_hp=custom_hp or None,
            X_train=X, y_train=y,
            task="classification" if is_classification else "regression",
            metric=flaml_metric,
            time_budget=search_budget,
            n_jobs=n_jobs,
            estimator_list=estimator_list,
            eval_method="cv",
            n_splits=N_SPLITS,
            split_type="stratified" if is_classification else "uniform",
            ensemble=False,          # the ensemble is built and evaluated below
            retrain_full=False,
            seed=SEED,
            verbose=0,
            log_file_name="",
            starting_points=starting_points or "static",
        )
    finally:
        done.set()
    search_time = time.time() - start
    check_stop()

    task = automl._state.task
    learner_classes = automl._state.learner_classes
    best_configs = {k: v for k, v in automl.best_config_per_estimator.items() if v is not None}
    best_losses = automl.best_loss_per_estimator
    if not best_configs and not previous_singles:
        raise ValueError("FLAML found no model in the time budget: increase the time out.")

    # specs (name, learner class, config) of the previous models, kept when not improved
    specs = {name: r["learner"].estimators[0] for name, r in previous_singles.items()}

    # continuation: re-evaluate only the algorithms whose FLAML loss improved
    kept = []
    candidates = []
    for name in sorted(best_configs, key=lambda e: best_losses.get(e, np.inf)):
        prev = previous_singles.get(name)
        if prev is not None and not best_losses.get(name, np.inf) < prev["flaml_loss"] - 1e-12:
            prev["run_status"] = "unchanged"
            kept.append(prev)
        else:
            candidates.append(name)
            specs[name] = (name, learner_classes[name], sanitize_config(best_configs[name]))
    for name, prev in previous_singles.items():
        if name not in best_configs:
            prev["run_status"] = "not relaunched" if name not in estimator_list else "unchanged"
            kept.append(prev)

    def estimated_cv_time(name):
        # time FLAML needed for its own 5-fold CV of this configuration
        state = automl._search_states.get(name)
        return float(getattr(state, "time2eval_best", 0) or 0)

    # --- 2. Cross-validated evaluation (progress 80 -> 100%) -----------------
    # Only cross-validation here: models trained on all data are built by the export.
    results, skipped = [], []
    # checked algorithms without result, shown at the bottom of the table with the reason
    not_trained = {name: NOT_TRAINED_NO_TRIAL for name in estimator_list
                   if name not in best_configs and name not in previous_singles}
    for i, name in enumerate(candidates):
        check_stop()
        learner = FlamlLearner([specs[name]], task, is_classification, n_jobs=n_jobs)
        # always evaluate the best configuration and the cheap ones (< 1 s);
        # skip the others if the time out would be exceeded
        estimate = estimated_cv_time(name)
        if results and estimate >= 1.0 and time.time() + estimate > deadline:
            skipped.append(learner.name)
            if name not in previous_singles:
                not_trained[name] = NOT_TRAINED_TIME_OUT
            continue
        lo, hi = 80 + 20 * i / len(candidates), 80 + 20 * (i + 1) / len(candidates)

        def cv_callback(p, lo=lo, hi=hi):
            check_stop()
            progress(lo + (hi - lo) * p)

        t0 = time.time()
        try:
            cv_results, metrics = cross_validate(learner, data, is_classification, callback=cv_callback)
        except AutoMLStopped:
            raise
        except Exception as e:
            print(f"AutoML: cross-validation of {learner.name} failed: {e}")
            skipped.append(f"{learner.name} (error: {e})")
            if name not in previous_singles:
                not_trained[name] = f"Not trained: error during the cross-validation ({e})"
            continue
        prev = previous_singles.get(name)
        results.append({
            "name": name,
            "label": learner.name,
            "config": specs[name][2],
            "flaml_loss": best_losses.get(name, np.nan),
            "metrics": metrics,
            "time": time.time() - t0,
            "cv_results": cv_results,
            "model": None,          # trained on all data by the export
            "learner": learner,
            "run_status": "new" if prev is None else "improved",
            "previous_metrics": None if prev is None else prev["metrics"],
        })
    # FLAML's loss comes from its own folds: a configuration better for FLAML may be worse on
    # the cross-validation shown in the table. Replace a previous model only if the new
    # configuration is strictly better on the ranking metric of OUR cross-validation.
    rank_name, higher_better = RANKING_METRIC[is_classification]
    for i, r in enumerate(results):
        prev = previous_singles.get(r["name"])
        if prev is None:
            continue
        new, old = r["metrics"][rank_name], prev["metrics"][rank_name]
        if not (new > old if higher_better else new < old):
            prev["run_status"] = "unchanged"
            prev["previous_metrics"] = prev["metrics"]
            results[i] = prev
    # a previous model whose improved version could not be evaluated is kept
    evaluated = {r["name"] for r in results}
    for name in candidates:
        if name not in evaluated and name in previous_singles:
            previous_singles[name]["run_status"] = "unchanged"
            kept.append(previous_singles[name])
    for r in kept:
        r["previous_metrics"] = r["metrics"]
    results += kept

    # Reference model with a frozen architecture (always evaluated, never tuned)
    reference_entry = _reference_entry(reference_model, previous, data, is_classification,
                                       skipped, check_stop)
    if reference_entry is not None:
        results.append(reference_entry)
    if not results:
        raise ValueError("All cross-validations failed.")

    rank_name, higher_better = RANKING_METRIC[is_classification]

    def rank_key(r):
        return -r["metrics"][rank_name] if higher_better else r["metrics"][rank_name]

    results.sort(key=rank_key)

    # Ensembles of the best single models, evaluated from their CV predictions (no extra training)
    singles = [r for r in results if r["name"] != "reference"]  # ensembles: FLAML models only
    ensembles = []
    if ensemble and len(singles) >= 2:
        ensembles.append(("ensemble", "voting", singles[:3], "Ensemble", voting_cv_results))
    if stacking and len(singles) >= 2:
        ensembles.append(("stacking", "stacking", singles[:5], "Stacking", stacking_cv_results))
    for name, method, top, title, evaluate in ensembles:
        check_stop()
        learner = FlamlLearner([specs[r["name"]] for r in top], task, is_classification, n_jobs=n_jobs,
                               method=method, name=f"{title} (" + " + ".join(r["label"] for r in top) + ")")
        try:
            cv_results, metrics = evaluate([r["cv_results"] for r in top], learner, is_classification)
        except Exception as e:
            print(f"AutoML: evaluation of {learner.name} failed: {e}")
            skipped.append(f"{learner.name} (error: {e})")
            continue
        config = {method: [r["name"] for r in top]}
        if method == "stacking":
            config["meta_model"] = type(make_meta_model(is_classification)).__name__
        prev = previous_ensembles.get(name)
        if prev is not None and prev["label"] == learner.name and all(
                r.get("run_status") == "unchanged" for r in top):
            prev["run_status"] = "unchanged"
            prev["previous_metrics"] = prev["metrics"]
            results.append(prev)  # same members, same configurations: keep it (and its trained model)
            continue
        results.append({
            "name": name,
            "label": learner.name,
            "config": config,
            "flaml_loss": np.nan,
            "metrics": metrics,
            "time": sum(r["time"] for r in top),
            "cv_results": cv_results,
            "model": None,
            "learner": learner,
            "run_status": "new" if prev is None else "rebuilt",
            "previous_metrics": None if prev is None else prev["metrics"],
        })
    results.sort(key=rank_key)

    # Fold-to-fold standard deviation of every metric + 1-SE rule recommendation
    for r in results:
        r["metrics_std"] = cv_fold_std(r["cv_results"], is_classification)
    one_se = apply_one_se_rule(results, rank_name, higher_better)

    # cv_results are kept: a later continuation re-uses those of the unchanged models
    evaluation_results = merge_results([r["cv_results"] for r in results], [r["label"] for r in results])

    # checked algorithms without result: placeholder rows at the end of the table
    names = metric_names(is_classification)
    for name, reason in not_trained.items():
        results.append({
            "name": name, "label": estimator_label(name), "config": {}, "flaml_loss": np.nan,
            "metrics": {n: np.nan for n in names}, "metrics_std": {}, "time": 0.0,
            "cv_results": None, "model": None, "learner": None,
            "run_status": "not trained", "previous_metrics": None,
            "untrained": True, "reason": reason,
        })

    progress(100)
    return {
        "task": "classification" if is_classification else "regression",
        "is_classification": is_classification,
        "target": target.name,
        "metric": flaml_metric,
        "ranking_metric": rank_name,
        "results": results,
        "evaluation_results": evaluation_results,
        "best_index": 0,
        "search_time": search_time,
        "total_time": time.time() - start,
        "skipped": skipped,
        "one_se": one_se,
        "n_runs": 1 if previous is None else previous["n_runs"] + 1,
        "cumulative_time": (time.time() - start) + (0 if previous is None else previous["cumulative_time"]),
        "searched": list(estimator_list),
        "reference_model": reference_model,
        "zero_shot": sorted(zero_shot_points),
    }


NOT_TRAINED_NO_TRIAL = ("Not trained: FLAML had no time to try this algorithm "
                        "(increase the time out, or uncheck other algorithms, then Continue search)")
NOT_TRAINED_TIME_OUT = ("Not evaluated: the time out was reached before its cross-validation "
                        "(increase the time out, then Continue search)")


def trained_results(automl_result):
    """Leaderboard entries that have a trained / cross-validated model (no placeholder rows)."""
    return [r for r in automl_result["results"] if not r.get("untrained")]


def metric_names(is_classification):
    if is_classification:
        return ["Accuracy", "Weighted F1", "F1", "Precision", "Recall", "AUC"]
    return ["RMSE", "MAE", "R2"]


def leaderboard_table(automl_result):
    """Orange Table with one row per model and the cross-validation metrics."""
    names = metric_names(automl_result["is_classification"])
    domain = Domain([ContinuousVariable(n) for n in names] + [ContinuousVariable(f"{n} std") for n in names]
                    + [ContinuousVariable("Time (s)")],
                    metas=[StringVariable("Model"), StringVariable("Algorithm"), StringVariable("1-SE rule"),
                           StringVariable("Configuration")])
    X, M = [], []
    for r in automl_result["results"]:
        std = r.get("metrics_std", {})
        X.append([r["metrics"][n] for n in names] + [std.get(n, np.nan) for n in names] + [r["time"]])
        M.append([r["label"], r["name"], one_se_text(r), r.get("reason") or str(r["config"])])
    return Table.from_numpy(domain, np.array(X, dtype=float).reshape(len(X), 2 * len(names) + 1),
                            metas=np.array(M, dtype=object).reshape(len(M), 4))


def one_se_text(r):
    if r.get("one_se_pick"):
        return "recommended"
    return "as good as the best" if r.get("within_1se") else ""
