"""
Orange-compatible Learner / Model wrapping FLAML estimators.

The produced models are true `Orange.base.Model` instances: they can be sent to
the "Predictions" widget, saved with "Save Model" (.pkcls) and reloaded with
"Load Model".

Preprocessing (imputation + one-hot encoding of discrete attributes) is done by
Orange preprocessors: the model's domain carries the transformations, so new
data are transformed automatically at prediction time.
Estimators that need scaled features (SGD, k-NN, linear models) carry their own
robust scaler (RobustScalingMixin).
"""
import numpy as np

from Orange.base import Learner, Model
from Orange.data.filter import HasClass
from Orange.preprocess import Impute, Continuize
from flaml import tune
from flaml.automl.model import (SGDEstimator, SKLearnEstimator, KNeighborsEstimator,
                                LRL2Classifier, ElasticNetEstimator)

N_SPLITS = 5
SEED = 42

DEFAULT_PREPROCESSORS = [HasClass(), Impute(), Continuize()]


def robust_center_scale(X):
    """
    Per column median and interquartile range (insensitive to outliers, unlike
    min-max or mean/std). 0/1 indicator columns (one-hot) are left unchanged
    (center 0, scale 1); a constant column falls back to its std, then to 1.
    """
    X = np.asarray(X, dtype=float)
    center = np.zeros(X.shape[1])
    scale = np.ones(X.shape[1])
    for j in range(X.shape[1]):
        col = X[:, j][np.isfinite(X[:, j])]
        if col.size == 0 or np.isin(np.unique(col), (0.0, 1.0)).all():
            continue
        center[j] = np.median(col)
        q1, q3 = np.percentile(col, [25, 75])
        s = q3 - q1
        if not s > 1e-12:
            s = col.std()
        scale[j] = s if s > 1e-12 else 1.0
    return center, scale


class RawSGDEstimator(SGDEstimator):
    """
    FLAML SGD on the features as they are.

    FLAML's own "sgd" applies sklearn's `Normalizer`, which rescales each ROW to unit
    L2 norm (it is not a column scaling and loses the magnitude of the rows): it is
    bypassed here.
    """
    def _preprocess(self, X):
        return np.asarray(SKLearnEstimator._preprocess(self, X), dtype=float)


class RobustScalingMixin:
    """
    Adds a built-in robust column scaling x -> (x - median) / IQR to a FLAML estimator
    (put it BEFORE the estimator class in the bases).

    The median / IQR are learned at fit time and stored in the estimator, so the
    scaling is applied automatically at prediction time (also after export / reload).
    It is a plain affine transformation without bounds: values outside the training
    range are extrapolated (no clipping, no NaN).
    """
    def _unscaled(self, X):
        # preprocessing of the wrapped estimator class (next in the MRO)
        return np.asarray(super()._preprocess(X), dtype=float)

    def _fit(self, X_train, y_train, **kwargs):
        self._scaling = robust_center_scale(self._unscaled(X_train))
        return super()._fit(X_train, y_train, **kwargs)

    def _preprocess(self, X):
        center, scale = self._scaling
        return (self._unscaled(X) - center) / scale


class ScaledSGDEstimator(RobustScalingMixin, RawSGDEstimator):
    """SGD with robust scaling."""


class ScaledKNeighborsEstimator(RobustScalingMixin, KNeighborsEstimator):
    """k-NN with robust scaling (distances are meaningless on unscaled features)."""


class ScaledLRL2Classifier(RobustScalingMixin, LRL2Classifier):
    """Logistic regression L2 with robust scaling (the penalty depends on the feature scale)."""


class ScaledElasticNetEstimator(RobustScalingMixin, ElasticNetEstimator):
    """Elastic Net regression with robust scaling (the penalty depends on the feature scale)."""


class XGBoostRFEstimator(SKLearnEstimator):
    """
    XGBoost Random Forest (XGBRFClassifier / XGBRFRegressor), as the
    "Extreme Gradient Boosting Random Forest (xgboost)" method of Orange.
    Not provided by FLAML: search space defined here.
    """
    @classmethod
    def search_space(cls, data_size, task, **params):
        n_rows = int(data_size[0])
        return {
            "n_estimators": {
                "domain": tune.lograndint(lower=4, upper=max(5, min(1024, n_rows))),
                "init_value": 4,
                "low_cost_init_value": 4,
            },
            "max_depth": {
                "domain": tune.randint(lower=2, upper=16),
                "init_value": 6,
                "low_cost_init_value": 2,
            },
            "min_child_weight": {
                "domain": tune.loguniform(lower=0.001, upper=128),
                "init_value": 1.0,
            },
            "subsample": {
                "domain": tune.uniform(lower=0.3, upper=1.0),
                "init_value": 0.8,
            },
            "colsample_bynode": {
                "domain": tune.uniform(lower=0.3, upper=1.0),
                "init_value": 0.8,
            },
            "reg_lambda": {
                "domain": tune.loguniform(lower=1e-5, upper=100),
                "init_value": 1e-5,
            },
        }

    @classmethod
    def cost_relative2lgbm(cls):
        return 2

    def __init__(self, task="binary", **config):
        super().__init__(task, **config)
        self.params.setdefault("random_state", SEED)
        self.params["verbosity"] = 0
        import xgboost
        if self._task.is_classification():
            self.estimator_class = xgboost.XGBRFClassifier
        else:
            self.estimator_class = xgboost.XGBRFRegressor


# estimators added to FLAML's built-in ones
CUSTOM_ESTIMATORS = {
    "sgd_raw": RawSGDEstimator,
    "sgd_scaled": ScaledSGDEstimator,
    "knn_scaled": ScaledKNeighborsEstimator,
    "lrl2_scaled": ScaledLRL2Classifier,
    "enet_scaled": ScaledElasticNetEstimator,
    "xgb_rf": XGBoostRFEstimator,
}

# Human-readable names of the FLAML estimators
ESTIMATOR_LABELS = {
    "lgbm": "LightGBM",
    "xgboost": "XGBoost",
    "xgb_limitdepth": "XGBoost (limited depth)",
    "xgb_rf": "XGBoost Random Forest",
    "histgb": "Hist Gradient Boosting (scikit-learn)",
    "rf": "Random Forest",
    "extra_tree": "Extra Trees",
    "catboost": "CatBoost",
    "lrl1": "Logistic Regression L1",
    "lrl2": "Logistic Regression L2",
    "lrl2_scaled": "Logistic Regression L2 (robust scaling)",
    "enet_scaled": "Elastic Net (robust scaling)",
    "sgd": "SGD (FLAML, row-normalized)",
    "sgd_raw": "SGD (no scaling)",
    "sgd_scaled": "SGD (robust scaling)",
    "kneighbor": "K-Nearest Neighbors",
    "knn_scaled": "K-Nearest Neighbors (robust scaling)",
    "ensemble": "Ensemble (voting)",
    "voting": "Ensemble (voting)",
    "stacking": "Stacking",
}


def estimator_label(name):
    return ESTIMATOR_LABELS.get(name, name)


def sanitize_config(config):
    """Remove FLAML-internal keys and convert numpy scalars to python types."""
    clean = {}
    for k, v in (config or {}).items():
        if k == "FLAML_sample_size":
            continue
        if isinstance(v, np.generic):
            v = v.item()
        if isinstance(v, float):
            v = round(v, 6)
        clean[k] = v
    return clean


def make_meta_model(is_classification):
    """Meta-model of the stacking: regularised linear model on the members' predictions."""
    if is_classification:
        from sklearn.linear_model import LogisticRegression
        return LogisticRegression(max_iter=2000)
    from sklearn.linear_model import RidgeCV
    return RidgeCV()


def build_flaml_estimator(learner_class, task, n_jobs, config):
    return learner_class(task=task, n_jobs=n_jobs, **sanitize_config(config))


class FlamlModel(Model):
    """Orange model wrapping a fitted FLAML estimator (or a stacking ensemble)."""

    def __init__(self, estimator, is_classification, domain=None, original_domain=None):
        super().__init__(domain, original_domain)
        self.estimator = estimator
        self.is_classification = is_classification

    def predict(self, X):
        X = np.asarray(X, dtype=float)
        # some estimators (CatBoost) return an (n, 1) array instead of (n,)
        value = np.asarray(self.estimator.predict(X), dtype=float).reshape(len(X))
        if self.is_classification and hasattr(self.estimator, "predict_proba"):
            probs = np.asarray(self.estimator.predict_proba(X), dtype=float)
            return value, probs
        return value

    def __repr__(self):
        return f"FlamlModel({getattr(self, 'name', '')})"


class FlamlLearner(Learner):
    """
    Orange learner training one FLAML estimator with a fixed configuration,
    or a stacking ensemble of several of them.

    :param estimators: list of (name, learner_class, config)
        - one element  -> single model
        - several      -> ensemble of these models ("voting" or "stacking", see `method`)
    :param task: FLAML task ("binary", "multiclass", "regression" or Task object)
    """
    preprocessors = DEFAULT_PREPROCESSORS
    __returns__ = FlamlModel

    def __init__(self, estimators, task, is_classification, n_jobs=1, name=None,
                 preprocessors=None, method="voting"):
        super().__init__(preprocessors=preprocessors)
        self.estimators = list(estimators)
        self.task = task
        self.is_classification = is_classification
        self.n_jobs = n_jobs
        self.method = method
        if name is None:
            name = (estimator_label(self.estimators[0][0]) if len(self.estimators) == 1
                    else estimator_label(method))
        self.name = name

    def _make_estimator(self):
        if len(self.estimators) == 1:
            _, learner_class, config = self.estimators[0]
            return build_flaml_estimator(learner_class, self.task, self.n_jobs, config)

        # Voting ensemble: mean of the probabilities (classification) or of the predictions
        # (regression). Unlike stacking there is no inner cross-validation, so it costs
        # only the training of its members, and its cross-validated predictions are
        # exactly the mean of the members' ones.
        base = [(name, build_flaml_estimator(learner_class, self.task, self.n_jobs, config))
                for name, learner_class, config in self.estimators]
        if self.method == "stacking":
            # meta-model trained on the 5-fold cross-validated predictions of the members
            from sklearn.ensemble import StackingClassifier, StackingRegressor
            from sklearn.model_selection import KFold, StratifiedKFold
            if self.is_classification:
                return StackingClassifier(
                    estimators=base, final_estimator=make_meta_model(True),
                    cv=StratifiedKFold(N_SPLITS, shuffle=True, random_state=SEED),
                    stack_method="predict_proba", n_jobs=1)
            return StackingRegressor(
                estimators=base, final_estimator=make_meta_model(False),
                cv=KFold(N_SPLITS, shuffle=True, random_state=SEED), n_jobs=1)
        if self.is_classification:
            from sklearn.ensemble import VotingClassifier
            return VotingClassifier(estimators=base, voting="soft", n_jobs=1)
        from sklearn.ensemble import VotingRegressor
        return VotingRegressor(estimators=base, n_jobs=1)

    def fit(self, X, Y, W=None):
        y = Y.ravel()
        if self.is_classification:
            y = y.astype(int)
        estimator = self._make_estimator()
        estimator.fit(np.asarray(X, dtype=float), y)
        return FlamlModel(estimator, self.is_classification)


# --------------------------------------------------------------------------------------
# Reference model with a frozen architecture
# --------------------------------------------------------------------------------------
class UnsupportedReferenceModel(ValueError):
    pass


def reference_template(model):
    """
    Un-fitted copy (sklearn.clone: same class and hyper-parameters, no learned weights) of
    the estimator inside an Orange model loaded with "Load Model".
    Supported: AutoML models (FlamlModel), Orange scikit-learn based models (SklModel:
    random forest, logistic regression, SVM, XGBoost, gradient boosting...) and CatBoost.
    """
    from sklearn.base import clone
    from Orange.base import SklModel, CatGBModel
    if isinstance(model, FlamlModel):
        estimator = model.estimator
    elif isinstance(model, SklModel):
        estimator = model.skl_model
    elif isinstance(model, CatGBModel):
        estimator = model.cat_model
    else:
        raise UnsupportedReferenceModel(
            f"'{getattr(model, 'name', type(model).__name__)}' ({type(model).__name__}) cannot be "
            f"re-trained with a frozen architecture: only AutoML models and Orange scikit-learn / "
            f"XGBoost / CatBoost based models are supported (not Orange's own Tree, Naive Bayes...).")
    try:
        template = clone(estimator)
    except Exception as e:
        raise UnsupportedReferenceModel(f"The estimator {type(estimator).__name__} cannot be cloned: {e}")
    # CatBoost from Orange: categorical columns are one-hot encoded here, no native categories
    if hasattr(template, "get_params") and "cat_features" in template.get_params(deep=False):
        template.set_params(cat_features=None)
    return template


def describe_template(template):
    """Short, readable description of the frozen hyper-parameters (Configuration column)."""
    params = getattr(template, "params", None)  # FLAML estimators
    if not isinstance(params, dict):
        try:
            params = template.get_params(deep=False)
        except Exception:
            params = {}
    simple = {k: v for k, v in sanitize_config(params).items()
              if isinstance(v, (int, float, str, bool)) and k not in ("n_jobs", "verbose", "verbosity")}
    members = getattr(template, "estimators", None)
    if isinstance(members, list) and members and isinstance(members[0], tuple):
        simple["members"] = [m[0] for m in members]
    return {"frozen": type(template).__name__, **simple}


class FrozenLearner(Learner):
    """
    Re-trains the architecture of a reference model (same estimator class and same
    hyper-parameters, NOT tuned) on new data, with the AutoML preprocessing
    (imputation + one-hot encoding).
    """
    preprocessors = DEFAULT_PREPROCESSORS
    __returns__ = FlamlModel

    def __init__(self, template, is_classification, name, preprocessors=None):
        super().__init__(preprocessors=preprocessors)
        self.template = template
        self.is_classification = is_classification
        self.name = name

    def fit(self, X, Y, W=None):
        from sklearn.base import clone
        y = Y.ravel()
        if self.is_classification:
            y = y.astype(int)
        estimator = clone(self.template)
        estimator.fit(np.asarray(X, dtype=float), y)
        return FlamlModel(estimator, self.is_classification)
