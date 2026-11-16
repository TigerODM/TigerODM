"""
Tooltips of the AutoML widget: what each statistic is and what it is used for.
Each tooltip is written in English, then in French.
Rich text (Qt tooltips accept simple HTML).
"""


def _block(title, what, use, use_label):
    return f"<b>{title}</b><br>{what}<br><i>{use_label}</i> {use}"


def _tip(en, fr):
    """en / fr: (title, what, what for)."""
    return ("<div style='white-space:normal; width:400px'>"
            + _block(*en, "What for:")
            + "<hr>"
            + _block(*fr, "À quoi ça sert :")
            + "</div>")


def _short(en, fr):
    """One-sentence bilingual tooltip."""
    return f"<div style='white-space:normal; width:400px'>{en}<hr>{fr}</div>"


METRIC_HELP = {
    "Accuracy": _tip(
        ("Accuracy (higher is better, 0 to 1)",
         "Share of rows whose class is correctly predicted.",
         "Easy to read, but misleading with imbalanced classes: always predicting the majority "
         "class of a 95/5 dataset already gives 0.95. Prefer F1 or AUC in that case."),
        ("Exactitude / Accuracy (plus haut = mieux, de 0 à 1)",
         "Part des lignes dont la classe est correctement prédite.",
         "Facile à lire, mais trompeuse si les classes sont déséquilibrées : prédire toujours la "
         "classe majoritaire d'un jeu 95/5 donne déjà 0,95. Préférez alors le F1 ou l'AUC.")),
    "Weighted F1": _tip(
        ("Weighted F1 (ODM F1) - weighted average (higher is better, 0 to 1)",
         "Harmonic mean of Precision and Recall, computed for each class then averaged with a "
         "weight equal to the number of rows of the class - same value as the F1 of Orange's Test & "
         "Score (target \"average over classes\"). Used to rank the models in classification.",
         "Main ranking metric. With very imbalanced classes the large classes dominate it: compare "
         "it with the F1 column (macro). Optimise it exactly with \"weighted_f1 (ODM F1)\"."),
        ("F1 pondéré (F1 ODM) - moyenne pondérée (plus haut = mieux, de 0 à 1)",
         "Moyenne harmonique de la Précision et du Rappel, calculée pour chaque classe puis moyennée "
         "avec un poids égal au nombre de lignes de la classe - même valeur que le F1 de Test & Score "
         "d'Orange (cible « average over classes »). Sert au classement des modèles en classification.",
         "Métrique principale du classement. Si les classes sont très déséquilibrées, les grandes "
         "classes dominent : comparez avec la colonne F1 (macro). Optimisez-la exactement avec "
         "« weighted_f1 (ODM F1) »."),
    ),
    "F1": _tip(
        ("F1 - macro average (higher is better, 0 to 1)",
         "Harmonic mean of Precision and Recall, computed for each class then averaged with the "
         "SAME weight for every class (not shown by Orange's Test & Score, which shows the weighted F1).",
         "Complements the Weighted F1: a rare class counts as much as a large one, so a model that "
         "neglects the small classes gets a lower F1. A big gap between Weighted F1 and F1 means the "
         "small classes are badly predicted. Optimise it with \"macro_f1\"."),
        ("F1 - moyenne macro (plus haut = mieux, de 0 à 1)",
         "Moyenne harmonique de la Précision et du Rappel, calculée pour chaque classe puis moyennée "
         "avec le MÊME poids pour toutes les classes (non affiché par Test & Score d'Orange, qui "
         "affiche le F1 pondéré).",
         "Complète le F1 pondéré : une classe rare compte autant qu'une grande, donc un modèle qui "
         "néglige les petites classes a un F1 plus bas. Un grand écart entre Weighted F1 et F1 "
         "signifie que les petites classes sont mal prédites. Optimisez-le avec « macro_f1 »."),
    ),
    "Precision": _tip(
        ("Precision, weighted average (higher is better, 0 to 1)",
         "Among the rows predicted in a class, share that really belongs to it (averaged over the "
         "classes, weighted by their number of rows, as Orange's Test & Score).",
         "Look at it when false alarms are costly (e.g. wrongly flagging a client as a fraudster)."),
        ("Précision, moyenne pondérée (plus haut = mieux, de 0 à 1)",
         "Parmi les lignes prédites dans une classe, part qui lui appartient vraiment (moyenne sur "
         "les classes, pondérée par leur nombre de lignes, comme Test & Score d'Orange).",
         "À regarder quand les fausses alertes coûtent cher (ex. accuser à tort un client de fraude).")),
    "Recall": _tip(
        ("Recall, weighted average (higher is better, 0 to 1)",
         "Among the rows of a class, share that the model finds (averaged over the classes, "
         "weighted by their number of rows, as Orange's Test & Score).",
         "Look at it when missing a case is costly (e.g. not detecting a failure or a disease)."),
        ("Rappel, moyenne pondérée (plus haut = mieux, de 0 à 1)",
         "Parmi les lignes d'une classe, part que le modèle retrouve (moyenne sur les classes, "
         "pondérée par leur nombre de lignes, comme Test & Score d'Orange).",
         "À regarder quand rater un cas coûte cher (ex. ne pas détecter une panne ou une maladie).")),
    "AUC": _tip(
        ("AUC - area under the ROC curve (higher is better, 0.5 = random, 1 = perfect)",
         "Probability that the model gives a higher score to a row of the class than to a row "
         "of another class. Computed as Orange's Test & Score: on each cross-validation fold then "
         "averaged; in multiclass, one-vs-rest AUC of each class weighted by c x (N - c). Uses the "
         "predicted probabilities, not only the predicted class.",
         "Measures how well the model ranks / separates the classes, whatever the decision threshold."),
        ("AUC - aire sous la courbe ROC (plus haut = mieux, 0,5 = hasard, 1 = parfait)",
         "Probabilité que le modèle donne un score plus élevé à une ligne de la classe qu'à une "
         "ligne d'une autre classe. Calculée comme Test & Score d'Orange : sur chaque pli de la "
         "validation croisée puis moyennée ; en multiclasse, AUC un-contre-tous de chaque classe "
         "pondérée par c x (N - c). Utilise les probabilités prédites, pas seulement la classe prédite.",
         "Mesure la capacité du modèle à ordonner / séparer les classes, quel que soit le seuil de décision.")),
    "RMSE": _tip(
        ("RMSE - root mean squared error (lower is better, in the unit of the target)",
         "Square root of the mean of the squared errors.",
         "Main ranking metric in regression. Large errors weigh much more than small ones: "
         "use it when big mistakes are especially bad."),
        ("RMSE - racine de l'erreur quadratique moyenne (plus bas = mieux, dans l'unité de la cible)",
         "Racine carrée de la moyenne des erreurs au carré.",
         "Métrique principale du classement en régression. Les grosses erreurs pèsent beaucoup plus "
         "que les petites : à utiliser quand les grosses erreurs sont particulièrement graves.")),
    "MAE": _tip(
        ("MAE - mean absolute error (lower is better, in the unit of the target)",
         "Mean of the absolute errors: the typical size of an error.",
         "The easiest to explain (\"on average we are wrong by X\"); less sensitive to a few "
         "large errors than RMSE."),
        ("MAE - erreur absolue moyenne (plus bas = mieux, dans l'unité de la cible)",
         "Moyenne des erreurs en valeur absolue : la taille typique d'une erreur.",
         "La plus simple à expliquer (« en moyenne on se trompe de X ») ; moins sensible que la "
         "RMSE à quelques grosses erreurs.")),
    "R2": _tip(
        ("R² - coefficient of determination (higher is better, 1 = perfect, 0 = predicting the mean)",
         "Share of the variance of the target explained by the model. Can be negative when the "
         "model is worse than always predicting the mean.",
         "Compare models independently of the unit of the target."),
        ("R² - coefficient de détermination (plus haut = mieux, 1 = parfait, 0 = prédire la moyenne)",
         "Part de la variance de la cible expliquée par le modèle. Peut être négatif si le modèle "
         "fait pire que prédire toujours la moyenne.",
         "Comparer des modèles indépendamment de l'unité de la cible.")),
}

OPTIMISATION_METRIC_HELP = {
    "macro_f1": _short(
        "FLAML maximises the macro F1 (all classes have the same weight): the F1 column of the "
        "table. Good default, robust to imbalanced classes. The ranking uses the Weighted F1 "
        "(Orange's F1): choose \"weighted_f1 (ODM F1)\" to optimise exactly that one.",
        "FLAML maximise le F1 macro (toutes les classes ont le même poids) : la colonne F1 du "
        "tableau. Bon choix par défaut, robuste aux classes déséquilibrées. Le classement utilise le "
        "Weighted F1 (le F1 d'Orange) : choisir « weighted_f1 (ODM F1) » pour optimiser exactement "
        "celui-là."),
    "weighted_f1 (ODM F1)": _short(
        "FLAML maximises the F1 weighted by the number of rows of each class: exactly the Weighted F1 "
        "column of the table and the F1 of Orange's Test & Score (ODM). The large classes count more.",
        "FLAML maximise le F1 pondéré par le nombre de lignes de chaque classe : exactement la colonne "
        "Weighted F1 du tableau et le F1 de Test & Score d'Orange (ODM). Les grandes classes comptent "
        "davantage."),
    "accuracy": _short(
        "FLAML maximises the accuracy. Only for balanced classes.",
        "FLAML maximise l'exactitude (accuracy). Seulement si les classes sont équilibrées."),
    "roc_auc": _short(
        "FLAML maximises the AUC (quality of the ranking given by the predicted probabilities).",
        "FLAML maximise l'AUC (qualité du classement donné par les probabilités prédites)."),
    "log_loss": _short(
        "FLAML minimises the log loss: rewards well calibrated probabilities.",
        "FLAML minimise la log loss : favorise des probabilités bien calibrées."),
    "rmse": _short(
        "FLAML minimises the RMSE: large errors are strongly penalised.",
        "FLAML minimise la RMSE : les grosses erreurs sont fortement pénalisées."),
    "r2": _short(
        "FLAML maximises the R² (equivalent to minimising the mean squared error).",
        "FLAML maximise le R² (équivaut à minimiser l'erreur quadratique moyenne)."),
    "mae": _short(
        "FLAML minimises the MAE: robust to a few large errors / outliers.",
        "FLAML minimise la MAE : robuste à quelques grosses erreurs / valeurs aberrantes."),
}

COLUMN_HELP = {
    "#": _tip(
        ("Rank",
         "Position in the cross-validation ranking (Weighted F1 in classification, RMSE in regression).",
         "Click on any header to sort by another column; click on # to come back to the ranking."),
        ("Rang",
         "Position dans le classement de la validation croisée (Weighted F1 en classification, RMSE en régression).",
         "Cliquez sur un en-tête pour trier selon une autre colonne ; cliquez sur # pour revenir au classement.")),
    "Model": _tip(
        ("Model",
         "Algorithm with the best hyper-parameters found by FLAML, or a combination "
         "(Ensemble = vote of the 3 best, Stacking = meta-model on the 5 best).",
         "Select one or several rows to export them or send them on the outputs."),
        ("Modèle",
         "Algorithme avec les meilleurs hyperparamètres trouvés par FLAML, ou une combinaison "
         "(Ensemble = vote des 3 meilleurs, Stacking = méta-modèle sur les 5 meilleurs).",
         "Sélectionnez une ou plusieurs lignes pour les exporter ou les envoyer sur les sorties.")),
    "CV time (s)": _tip(
        ("CV time (s)",
         "Time spent by the 5-fold cross-validation of the model (for ensembles: sum of their members).",
         "Gives an idea of the training cost of the model."),
        ("Temps de CV (s)",
         "Temps passé par la validation croisée à 5 plis du modèle (pour les ensembles : somme de leurs membres).",
         "Donne une idée du coût d'entraînement du modèle.")),
    "Configuration": _tip(
        ("Configuration",
         "Hyper-parameters found by the FLAML search.",
         "Lets you reproduce the model, or understand its complexity "
         "(number of trees, depth, regularisation...)."),
        ("Configuration",
         "Hyperparamètres trouvés par la recherche FLAML.",
         "Permet de reproduire le modèle ou de comprendre sa complexité "
         "(nombre d'arbres, profondeur, régularisation...).")),
    "std": _tip(
        ("Fold-to-fold standard deviation",
         "Standard deviation of the score across the 5 cross-validation folds.",
         "Tells whether a difference between two models is real or just noise: if two scores "
         "differ by less than about one std, they are not really different. A large std means an "
         "unstable model or too little data."),
        ("Écart-type entre les plis",
         "Écart-type du score entre les 5 plis de la validation croisée.",
         "Indique si une différence entre deux modèles est réelle ou due au hasard : si deux scores "
         "diffèrent de moins d'environ un écart-type, ils ne sont pas vraiment différents. Un grand "
         "écart-type signale un modèle instable ou trop peu de données.")),
    "1-SE rule": _tip(
        ("1-SE rule (one standard error rule)",
         "Models whose CV score is within one standard error (std / √5) of the best one are "
         "statistically as good as the best (\"≈ best\"). Among them, the simplest is "
         "<b>recommended</b> (linear &lt; k-NN &lt; forests &lt; boosting &lt; ensembles).",
         "Fights over-fitting of the model SELECTION: with many models, the top score is partly "
         "luck; a simpler model of equivalent score generalises more safely."),
        ("Règle 1-SE (règle d'une erreur standard)",
         "Les modèles dont le score de CV est à moins d'une erreur standard (écart-type / √5) du "
         "meilleur sont statistiquement aussi bons que lui (« ≈ best »). Parmi eux, le plus simple "
         "est <b>recommandé</b> (linéaire &lt; k-NN &lt; forêts &lt; boosting &lt; ensembles).",
         "Limite le sur-apprentissage du CHOIX du modèle : avec beaucoup de modèles, le meilleur "
         "score est en partie dû à la chance ; un modèle plus simple de score équivalent "
         "généralise plus sûrement.")),
    "Train": _tip(
        ("Train score",
         "Score of the model re-trained on all the training data, measured on these same data.",
         "Always optimistic. Compared with the CV score it reveals memorisation (see Train−CV gap)."),
        ("Score d'apprentissage",
         "Score du modèle réentraîné sur toutes les données d'apprentissage, mesuré sur ces mêmes données.",
         "Toujours optimiste. Comparé au score de CV, il révèle l'apprentissage par cœur "
         "(voir Train−CV gap).")),
    "CV": _tip(
        ("Cross-validation score",
         "Mean score over the 5 folds: each row is predicted by a model that never saw it.",
         "Used to choose the model. Slightly optimistic when many models are compared "
         "(the best one is partly lucky)."),
        ("Score de validation croisée",
         "Score moyen sur les 5 plis : chaque ligne est prédite par un modèle qui ne l'a jamais vue.",
         "Sert à choisir le modèle. Légèrement optimiste quand on compare beaucoup de modèles "
         "(le meilleur a en partie de la chance).")),
    "Validation": _tip(
        ("Validation score (hold-out)",
         "Score on the validation data, never used by the search, the cross-validation nor the "
         "choice of the model.",
         "The most honest estimate of the performance on new data."),
        ("Score de validation (hold-out)",
         "Score sur les données de validation, jamais utilisées par la recherche, la validation "
         "croisée ni le choix du modèle.",
         "L'estimation la plus honnête de la performance sur de nouvelles données.")),
    "CI": _tip(
        ("95 % confidence interval of the validation score (bootstrap)",
         "The validation rows are resampled with replacement 500 times (100 for AUC) and the "
         "score recomputed; the interval contains 95 % of these scores.",
         "Shows the uncertainty due to the size of the validation set: if the intervals of two "
         "models overlap a lot, the validation cannot separate them."),
        ("Intervalle de confiance à 95 % du score de validation (bootstrap)",
         "Les lignes de validation sont rééchantillonnées avec remise 500 fois (100 pour l'AUC) et "
         "le score recalculé ; l'intervalle contient 95 % de ces scores.",
         "Montre l'incertitude due à la taille du jeu de validation : si les intervalles de deux "
         "modèles se recouvrent largement, la validation ne permet pas de les départager.")),
    "Drift CV→Val": _tip(
        ("Drift from CV to validation",
         "Relative degradation of the score between the cross-validation and the validation data "
         "(orange &gt; 5 %, red &gt; 15 %).",
         "Detects over-fitting of the model selection, or a difference between the training and "
         "validation data (data shift). Compare with the confidence interval: a drift inside the "
         "interval may just be noise."),
        ("Dérive de la CV vers la validation",
         "Dégradation relative du score entre la validation croisée et les données de validation "
         "(orange &gt; 5 %, rouge &gt; 15 %).",
         "Détecte le sur-apprentissage du choix du modèle, ou une différence entre les données "
         "d'apprentissage et de validation (dérive des données). À comparer avec l'intervalle de "
         "confiance : une dérive contenue dans l'intervalle peut n'être que du bruit.")),
    "Train−CV gap": _tip(
        ("Train − CV gap",
         "Relative difference between the score on the training data and the cross-validation score.",
         "Measures memorisation: a large gap (e.g. k-NN, deep trees) means the model learns the "
         "training rows by heart. Not a problem in itself if the CV / validation scores stay good."),
        ("Écart apprentissage − CV",
         "Différence relative entre le score sur les données d'apprentissage et le score de "
         "validation croisée.",
         "Mesure l'apprentissage par cœur : un grand écart (ex. k-NN, arbres profonds) signifie que "
         "le modèle retient les lignes d'apprentissage. Pas un problème en soi si les scores de CV / "
         "validation restent bons.")),
}

COLUMN_HELP["Last run"] = _tip(
    ("Last run",
     "What the last \"Continue search\" did to this model: <b>improved</b> (better configuration "
     "found and re-evaluated), <b>unchanged</b> (searched again, nothing better found: kept as is), "
     "<b>not relaunched</b> (algorithm unchecked: kept as is), <b>new</b> (first evaluation), "
     "<b>rebuilt</b> (ensemble whose members changed), <b>frozen</b> (reference model: architecture not tuned), <b>not trained</b> (checked but no time / error).",
     "See which algorithms benefited from the extra time."),
    ("Dernier run",
     "Ce que le dernier « Continue search » a fait à ce modèle : <b>improved</b> (meilleure "
     "configuration trouvée et réévaluée), <b>unchanged</b> (recherché de nouveau, rien de mieux : "
     "gardé tel quel), <b>not relaunched</b> (algorithme décoché : gardé tel quel), <b>new</b> "
     "(première évaluation), <b>rebuilt</b> (ensemble dont les membres ont changé), <b>frozen</b> (modèle de référence : architecture non réglée), <b>not trained</b> (coché mais pas de temps / erreur).",
     "Voir quels algorithmes ont profité du temps supplémentaire."))

COLUMN_HELP["Δ"] = _tip(
    ("Δ - gain versus the previous run",
     "Relative change of the cross-validation score of the model since the previous run "
     "(positive = better, green). 0 for kept models, empty for new ones.",
     "Measure the benefit of the extra time. Compare it with the std column: a gain smaller than "
     "the fold-to-fold standard deviation may be noise."),
    ("Δ - gain par rapport au run précédent",
     "Variation relative du score de validation croisée du modèle depuis le run précédent "
     "(positif = mieux, en vert). 0 pour les modèles conservés, vide pour les nouveaux.",
     "Mesurer le bénéfice du temps supplémentaire. À comparer avec la colonne std : un gain plus "
     "petit que l'écart-type entre les plis peut n'être que du bruit."))

NOT_TRAINED_HELP = _tip(
    ("Not trained",
     "This algorithm was checked, but has no result: FLAML had no time to try it, or the time out "
     "was reached before its cross-validation, or an error occurred (reason below). The row has no "
     "score and cannot be exported nor evaluated on the validation data.",
     "Know which checked algorithms were not compared. Give more time (time out, or Continue search "
     "with only these algorithms checked) to include them."),
    ("Non entraîné",
     "Cet algorithme était coché mais n'a pas de résultat : FLAML n'a pas eu le temps de l'essayer, "
     "ou le time out a été atteint avant sa validation croisée, ou une erreur s'est produite (raison "
     "ci-dessous). La ligne n'a pas de score et ne peut être ni exportée ni évaluée sur les données "
     "de validation.",
     "Savoir quels algorithmes cochés n'ont pas été comparés. Donnez plus de temps (time out, ou "
     "Continue search en ne cochant que ces algorithmes) pour les inclure."))

REFERENCE_HELP = _tip(
    ("Reference model - frozen architecture [frozen]",
     "Model given on the optional \"Reference Model\" input (e.g. a model chosen before and loaded "
     "with \"Load Model\"). Its architecture is FROZEN: same algorithm and same hyper-parameters, "
     "never tuned by FLAML. Only its weights are re-learned: it is cross-validated on the current "
     "training data (5 folds, same folds as the other models), can be evaluated on the validation "
     "data and exported (re-trained on all the training data). Preprocessing: imputation + one-hot "
     "encoding, like the AutoML models. It is not used in the voting / stacking ensembles.",
     "Check whether the model chosen before is still the best on the new data, or whether FLAML "
     "finds better."),
    ("Modèle de référence - architecture figée [frozen]",
     "Modèle fourni sur l'entrée facultative « Reference Model » (ex. un modèle choisi auparavant et "
     "chargé avec « Load Model »). Son architecture est FIGÉE : même algorithme et mêmes "
     "hyperparamètres, jamais réglés par FLAML. Seuls ses poids sont réappris : il est évalué en "
     "validation croisée sur les données d'apprentissage actuelles (5 plis, les mêmes que les autres "
     "modèles), peut être évalué sur les données de validation et exporté (réentraîné sur toutes les "
     "données d'apprentissage). Prétraitement : imputation + one-hot, comme les modèles AutoML. Il "
     "n'entre pas dans les ensembles (vote / stacking).",
     "Vérifier si le modèle choisi auparavant reste le meilleur sur les nouvelles données, ou si "
     "FLAML trouve mieux."))

PARAM_HELP = {
    "check_zero_shot": _tip(
        ("Zero-shot start (FLAML portfolio)",
         "FLAML was run in advance on hundreds of public datasets; from these results it keeps a "
         "catalogue of good configurations (installed with FLAML, nothing is downloaded). When checked, "
         "LightGBM, Random Forest, Extra Trees and XGBoost start their search from the configuration "
         "the catalogue suggests for data of this shape, instead of a tiny one (4 trees, 4 leaves). It is "
         "only a starting point: no pre-trained weights, the models are still trained on your data. "
         "The values are clipped to the bounds of the search space. Other algorithms are not affected; "
         "with Continue search it only applies to algorithms without a previous result.",
         "Useful on LARGE data with a comfortable time out. On small data or with a short time out it "
         "is often WORSE: the suggested models are heavy (hundreds of trees), so fewer trials are done, "
         "some algorithms may stay untrained and the time out can be exceeded. Measured on 300-500 rows: "
         "mostly no gain."),
        ("Démarrage zero-shot (catalogue FLAML)",
         "FLAML a été lancé à l'avance sur des centaines de jeux de données publics ; il en a tiré un "
         "catalogue de bonnes configurations (installé avec FLAML, rien n'est téléchargé). Si la case est "
         "cochée, LightGBM, Random Forest, Extra Trees et XGBoost démarrent leur recherche depuis la "
         "configuration que le catalogue propose pour des données de cette forme, au lieu d'une "
         "configuration minuscule (4 arbres, 4 feuilles). Ce n'est qu'un point de départ : aucun poids "
         "pré-entraîné, les modèles sont toujours entraînés sur vos données. Les valeurs sont ramenées dans "
         "les bornes de l'espace de recherche. Les autres algorithmes ne sont pas concernés ; avec Continue "
         "search, seuls les algorithmes sans résultat précédent en profitent.",
         "Utile sur de GROSSES données avec un time out confortable. Sur de petites données ou avec un "
         "time out court, c'est souvent MOINS bon : les modèles proposés sont lourds (des centaines "
         "d'arbres), donc moins d'essais, certains algorithmes peuvent rester non entraînés et le time out "
         "peut être dépassé. Mesuré sur 300 à 500 lignes : pas de gain en général.")),
    "pushButton_check_all": _tip(
        ("Check all / Uncheck all",
         "Checks all the algorithms; if they are all already checked, unchecks them all.",
         "Quickly start from everything, or from nothing to check only a few algorithms "
         "(e.g. before a Continue search)."),
        ("Tout cocher / Tout décocher",
         "Coche tous les algorithmes ; s'ils sont déjà tous cochés, les décoche tous.",
         "Partir rapidement de tout, ou de rien pour ne cocher que quelques algorithmes "
         "(ex. avant un Continue search).")),
    "label_reference": REFERENCE_HELP,
    "spin_extra": _tip(
        ("Extra time (s)",
         "Duration of a \"Continue search\" (search + cross-validation of the improved models).",
         "Give more time only where it is useful, without restarting from zero."),
        ("Temps supplémentaire (s)",
         "Durée d'un « Continue search » (recherche + validation croisée des modèles améliorés).",
         "Donner plus de temps seulement là où c'est utile, sans repartir de zéro.")),
    "pushButton_continue": _tip(
        ("Continue search on checked algorithms",
         "Searches again, during the extra time, ONLY the checked algorithms, starting from their best "
         "configuration found so far (FLAML warm start). A model is re-evaluated only if a better "
         "configuration is found; unchecked algorithms keep their results. Ensembles, stacking, std "
         "and 1-SE rule are recomputed. Same data and same optimisation metric as the first run.",
         "Improve the promising algorithms (or those which had few trials) without restarting "
         "everything. Uncheck the others to give them all the time."),
        ("Continuer la recherche sur les algorithmes cochés",
         "Relance la recherche, pendant le temps supplémentaire, UNIQUEMENT sur les algorithmes "
         "cochés, en partant de leur meilleure configuration trouvée jusqu'ici (démarrage à chaud "
         "FLAML). Un modèle n'est réévalué que si une meilleure configuration est trouvée ; les "
         "algorithmes décochés gardent leurs résultats. Ensembles, stacking, écart-type et règle 1-SE "
         "sont recalculés. Mêmes données et même métrique d'optimisation que le premier run.",
         "Améliorer les algorithmes prometteurs (ou ceux qui ont eu peu d'essais) sans tout "
         "recommencer. Décochez les autres pour leur laisser tout le temps.")),
    "export_from_validation": _tip(
        ("Export selected models",
         "Saves the selected models (.pkcls) in the export folder. They are trained on ALL the "
         "training data and NEVER on the validation data; the first one is also sent on the "
         "\"Model\" output.",
         "Keep the model(s) chosen after the validation, to use them with 'Load Model' and "
         "'Predictions'. Ctrl / Shift + click to select several."),
        ("Exporter les modèles sélectionnés",
         "Enregistre les modèles sélectionnés (.pkcls) dans le dossier d'export. Ils sont entraînés "
         "sur TOUTES les données d'apprentissage et JAMAIS sur les données de validation ; le "
         "premier est aussi envoyé sur la sortie « Model ».",
         "Conserver le ou les modèles choisis après la validation, pour les utiliser avec "
         "« Load Model » et « Predictions ». Ctrl / Maj + clic pour en sélectionner plusieurs.")),
    "check_ensemble": _tip(
        ("Voting ensemble",
         "Averages the probabilities (or predictions) of the 3 best models.",
         "Reduces the variance: often more stable on new data than each model alone."),
        ("Ensemble par vote",
         "Fait la moyenne des probabilités (ou des prédictions) des 3 meilleurs modèles.",
         "Réduit la variance : souvent plus stable sur de nouvelles données que chaque modèle seul.")),
    "check_stacking": _tip(
        ("Stacking",
         "A linear meta-model learns how to combine the predictions of the 5 best models "
         "(trained on their cross-validated predictions).",
         "Can beat the best single model when the models make different errors."),
        ("Stacking",
         "Un méta-modèle linéaire apprend à combiner les prédictions des 5 meilleurs modèles "
         "(entraîné sur leurs prédictions de validation croisée).",
         "Peut battre le meilleur modèle seul quand les modèles font des erreurs différentes.")),
    "spin_time": _tip(
        ("Time out",
         "Maximum duration of the whole run (search + cross-validation).",
         "More time = more hyper-parameter trials = better and more stable models."),
        ("Durée maximale (time out)",
         "Durée maximale de tout le calcul (recherche + validation croisée).",
         "Plus de temps = plus d'essais d'hyperparamètres = des modèles meilleurs et plus stables.")),
    "spin_threads": _tip(
        ("Threads",
         "Number of CPU cores used by the training.",
         "Leave one core free to keep Orange responsive."),
        ("Threads",
         "Nombre de cœurs CPU utilisés pour l'entraînement.",
         "Laissez un cœur libre pour qu'Orange reste réactif.")),
    "pushButton_validate": _tip(
        ("Evaluate on validation data",
         "Re-trains every model on all the training data and scores it on the validation data "
         "(never used before), with a 95 % confidence interval.",
         "Checks the over-fitting and gives an honest estimate of the performance."),
        ("Évaluer sur les données de validation",
         "Réentraîne chaque modèle sur toutes les données d'apprentissage et le note sur les données "
         "de validation (jamais utilisées auparavant), avec un intervalle de confiance à 95 %.",
         "Vérifie le sur-apprentissage et donne une estimation honnête de la performance.")),
}


SEPARATOR = "<br><div style='border-top:3px double #888'></div><br>"


def _join(*parts):
    return SEPARATOR.join(p for p in parts if p)


def column_help(header):
    """Tooltip for a table header like 'F1', 'CV F1', 'Val RMSE', 'F1 std'..."""
    if header in COLUMN_HELP:
        return COLUMN_HELP[header]
    if header.startswith("Δ "):
        return _join(COLUMN_HELP["Δ"], METRIC_HELP.get(header[2:], ""))
    for prefix, key in (("Train ", "Train"), ("CV ", "CV"), ("Validation ", "Validation"), ("Val ", "Validation")):
        if header.startswith(prefix):
            metric = header[len(prefix):]
            if metric.endswith(" std"):
                return _join(COLUMN_HELP["std"], METRIC_HELP.get(metric[:-4], ""))
            if metric.endswith(" 95% CI"):
                return _join(COLUMN_HELP["CI"], METRIC_HELP.get(metric[:-7], ""))
            return _join(COLUMN_HELP[key], METRIC_HELP.get(metric, ""))
    if header.endswith(" std"):
        return _join(COLUMN_HELP["std"], METRIC_HELP.get(header[:-4], ""))
    return METRIC_HELP.get(header, "")
