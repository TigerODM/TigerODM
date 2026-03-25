import sys
import time

import optuna

# écriture du CSV
# premiere ligne correspond au nom des variables et aux scores
# la deuxième ligne correspond au min de chaque variable, on met un ? pour les scores
# la troisième ligne correspond au max de chaque variable, on met un ? pour les scores
# la quatrième ligne correspond au step de chaque variable, on met un ? pour les scores (cette ligne est la seule qui n'est pas obligatoire pour faire marcher le script)
#
# exemple de CSV
# Definition du problème
# var1, var2, var3, score
# 1,0,10,?
# 10,1,100,?
# 1,0.01,10,?
# Historique des essais
# 1,0.1,10,1 (score de 1 pour var1=1, var2=1, var3=1)
# 2,0.2,20,2 (score de 2 pour var1=2, var2=2, var3=2)
# 3,0.3,30,3 (score de 3 pour var1=3, var2=3, var3=3)


# Exemple: La variable 1 va de 1 à 10, avec un step de 1.
# Score est la valeur à optimiser (minimiser)
# pour faire marcher ce script il faut passer le chemin du CSV en argument
# exemple de commande pour lancer le script:
# chemin_vers_python chemin_vers_ce_script chemin_vers_le_csv


# lecture du fichier csv et controle sur les dimensions
# 0 ok
# 1 No,
# le resultat est passé sous la variable mutable tableau_out en cas de success
def lecture_fichier_csv(filename, tableau_out):
    del tableau_out[:]
    tableau = []
    try:
        with open(filename, 'r') as file:
            tableau = file.readlines()
            # suppresion du \n en fin de ligne
            for idx, element in enumerate(tableau):
                if element[-1] == "\n":
                    tableau[idx] = tableau[idx][:-1]
            file.close()
    except:
        print("erreur a la lecture de ", filename)
        return 1
    for element in tableau:
        if len(element)<2:
            continue # une seule colonne ou 0 pas possible d avoir score & variable
        tableau_out.append(element.split(","))
    if len(tableau_out) < 3:
        print("erreur a la lecture du tableau il faut au moins 3 lignes")
        return 1
    nb_element = len(tableau_out[0])
    for element in tableau_out:
        if nb_element != len(element):
            print("erreur cette ligne n a pas le bon nombre de colonne", element)
            return 1
    # on verifie que les titres des colonnes sont bien tous differents
    premiere_ligne = tableau_out[0]
    # si l entete a des doublons on dit que c'est pas bon
    if len(premiere_ligne) != len(set(premiere_ligne)):
        print("erreur nom de colonne contient des doublons")
        return 1
    return 0


# True si il y a le step d indiqué
# False Sinon
def StepDansLefile(contenu_csv):
    # le Step est eventuellement indiqué sur la 4eme ligne
    # que 3 lignes -> pas de step
    if len(contenu_csv) == 3:
        return False
    contenu_4eme_ligne = contenu_csv[3]
    # un step n a lieu que lorsque sur une colone les lignes 2 3 4 sont à ?
    if '?' not in contenu_4eme_ligne:
        return False
    # si on a que des ? sur la 4eme ligne on a pas de step
    if all(x == "?" for x in contenu_4eme_ligne):
        return False
    for idx, element in enumerate(contenu_4eme_ligne):
        if element == '?':
            if contenu_csv[1][idx] == "?" and contenu_csv[2][idx] == "?":
                return True
    return False


# recupere le domaine d inference (borne min et max par dimension) a appliquer en gerant si il y a un step de specifié
def get_distributions(contenu_du_csv):
    distributions = {}
    # on commence par chercher si on est dans le cas avec ou sans step
    avec_step = StepDansLefile(contenu_du_csv)
    # creation des distributions et des scores
    ligne_0 = contenu_du_csv[0]
    for idx, element in enumerate(ligne_0):
        if element == "":
            continue
        if contenu_du_csv[1][idx] != "?" and contenu_du_csv[2][idx] != "?":
            # nom_colonne = element
            # si borne min et max sont inversés on remet dans le bon sens, trop gentil
            if contenu_du_csv[1][idx] == '':
                continue
            if contenu_du_csv[2][idx] == '':
                continue

            borne_min = min(float(contenu_du_csv[1][idx]), float(contenu_du_csv[2][idx]))
            brone_max = max(float(contenu_du_csv[1][idx]), float(contenu_du_csv[2][idx]))
            le_step = -1
            if avec_step:
                if contenu_du_csv[3][idx] != "?":
                    le_step = float(contenu_du_csv[3][idx])
            if le_step > 0:
                distributions[element] = optuna.distributions.FloatDistribution(borne_min, brone_max, step=le_step)
            else:
                # step negatif = pas de step
                distributions[element] = optuna.distributions.FloatDistribution(borne_min, brone_max)
    return distributions


# on recupere les noms des scores à etudier
def get_nom_scores_a_etudier(contenu_du_csv):
    liste_des_scores = []
    ligne_0 = contenu_du_csv[0]
    for idx, element in enumerate(ligne_0):
        if element == "":
            continue
        if contenu_du_csv[1][idx] == "?" and contenu_du_csv[2][idx] == "?":
            liste_des_scores.append(element)
    return liste_des_scores

#on crée l'etude optuna
def create_study(contenu_csv, liste_des_noms_de_scores, distributions, param_score_previous_study, trial= False):
    #verif sur le nombre de score deja fait dans main
    if len(liste_des_noms_de_scores) == 1:
        study = optuna.create_study(sampler=optuna.samplers.TPESampler(), direction="minimize")
    else:
        directions_etude = []
        for i in range(len(liste_des_noms_de_scores)):
            directions_etude.append("minimize")
        study = optuna.create_study(sampler=optuna.samplers.MOTPESampler(), directions=directions_etude)
    ## add_trial
    for idx, elem in enumerate(param_score_previous_study):
        # je comprend pas pourquoi il faut un [0] mais sinon ca plante au bout d une dizaine d iteration
        if len(elem['scores'])==1:
            study.add_trial(
                optuna.trial.create_trial(
                params=elem['params'],
                distributions=distributions,
                values=[elem['scores'][0]]
                )
            )
        else :
            study.add_trial(
                optuna.trial.create_trial(
                    params=elem['params'],
                    distributions=distributions,
                    values=elem['scores']
                )
            )
    best_params = []
    if len(param_score_previous_study) > 0 and len(liste_des_noms_de_scores) == 1:
        best_params.append({'params':study.best_params})

    if trial == False:
        if len(param_score_previous_study) > 0 and len(liste_des_noms_de_scores) > 1:
            ## plusieurs résultats en multi voir pour comment récupérer le meilleur
            #print(study.best_trials)

            for trial in study.best_trials:
                best_params.append({'params':trial.params, 'scores': trial.values})

    trial_params = []
    ## ask
    if trial == True:
        n_trials = 1
        for _ in range(n_trials):
            # Demande de nouveaux paramètres en utilisant les distributions définies
            trial = study.ask(distributions)
            trial_params.append(trial.params)
    return trial_params, best_params

# /!\ le fichier out doit etre egal au fichier d entree il s 'agit une mise à jour
def create_ligne_from_trial_params_csv(fichier_out,trial_params, contenu_csv, liste_des_noms_de_scores):
    for j in range(len(trial_params)):
        # on ajoute au contenu_csv l'etude optuna
        ligne = []
        for i, elem in enumerate(contenu_csv[0]):
            if elem in trial_params[j].keys():
                ligne.append(str(trial_params[j][elem]))
                continue
            if elem in liste_des_noms_de_scores:
                ligne.append("?")
                continue
            else:
                ligne.append("")
        contenu_csv.append(ligne)
    try:
        with open(fichier_out, "w") as f:
            # on rempli le fichier CSV par l'etude optuna
            for i in range(len(contenu_csv)):
                ligne = ''
                for j in range(len(contenu_csv[i])):
                    ligne += contenu_csv[i][j]
                    if j+1 != len(contenu_csv[i]):
                        ligne += ","
            # Écrire dans le fichier
                f.write(str(ligne))
                f.write("\n")
            f.close()
    except Exception as error:
        print("erreur a l ecriture de ", fichier_out)
        print("An exception occurred:", error)
        return 1
    return 0

# je les les anciennes études completes (avec entrées et les scores associés)
def get_param_score_previous_study(contenu_du_csv, distributions, liste_des_noms_de_scores):
    step = StepDansLefile(contenu_du_csv)
    if step == True:
        start_ligne = 4
    else:
        start_ligne = 3
    param_score_previous_study = []
    for idx, element in enumerate(contenu_du_csv):
        # je passe le début du fichier
        if idx< start_ligne:
            continue
        # je regarde si il y a des ? et des '' sur les elements si c est le cas on ignore la ligne
        passer_la_ligne=False
        for i in range(len(contenu_du_csv[0])):
            if contenu_du_csv[0][i] in distributions.keys() or contenu_du_csv[0][i] in liste_des_noms_de_scores:
                if element[i] in ('', '?'):
                    passer_la_ligne=True
                    break
        if passer_la_ligne:
            continue
        # j ajoute les infos
        params = {}
        scores = []
        for i in range(len(contenu_du_csv[0])):
            if contenu_du_csv[0][i] in distributions.keys():
                params.update({contenu_du_csv[0][i]: float(element[i])})
            if contenu_du_csv[0][i] in liste_des_noms_de_scores:
                scores.append(float(element[i]))
        if scores != [] and params != {}:
            param_score_previous_study.append({'params': params, 'scores':scores})
    return param_score_previous_study

# renvoie 0 si ok 1 si erreur
# lecture du fichier csv (separateur ,)
# ajoute un jeu de parametre en focntions des parametres et des scores precedents obtenus
def complete_fichier_avec_proposition_optuna(filename):
    contenu_csv = []
    if 0 != lecture_fichier_csv(filename, contenu_csv):
        print("erreur a la lecture de ", filename)
        return 1
    domaine_inference_a_etudier = get_distributions(contenu_csv)
    if len(domaine_inference_a_etudier) == 0:
        print("erreur pas de domaine d inference")
        return 1
    liste_des_noms_de_scores = get_nom_scores_a_etudier(contenu_csv)
    if len(liste_des_noms_de_scores) == 0:
        print("erreur aucun score")
        return 1
    # if len(liste_des_noms_de_scores) != 1:
    #     print("erreur pour l instant je ne gere qu un seul score dans l implementation")
    #     return 1
    # print(domaine_inference_a_etudier)
    param_score_previous_study = get_param_score_previous_study(contenu_csv, domaine_inference_a_etudier, liste_des_noms_de_scores)
    trial_params = create_study(contenu_csv, liste_des_noms_de_scores, domaine_inference_a_etudier, param_score_previous_study)
    if trial_params == []:
        print("erreur pas de paramètres créés")
        return 1
    if 0!=create_ligne_from_trial_params_csv(filename,trial_params, contenu_csv, liste_des_noms_de_scores):
        print("erreur a l ecriture de ",filename)
        return 1
    return 0

def get_domain_and_data_from_previous_study(score, len_score, current_data_search_space, current_data_previous_study):
    data = []
    domain = []
    for i in range(len(current_data_search_space.domain)):
        domain.append(current_data_search_space.domain[i].name)
    if score is None and len_score is None:
        domain.append('score')
    else:
        for i in range(len_score):
            domain.append('score'+str(i))

    for i in range(len(current_data_search_space)):
        d = []
        for j in range(len(current_data_search_space.domain)):
            d.append(current_data_search_space[i][j].value)
        ## pour le paramètrage premiere iteration ajout d'un ? à la fin de la ligne
        if score is None and len_score is None:
            d.append('?')
        else:
            for i in range(len_score):
                d.append('?')
        data.append(d)
    if current_data_previous_study is not None:
        #pour eviter de rentre dans ce cas lors de la première étude dure de définir plusieurs score à l'init
        if len(current_data_previous_study) > 1:
            if len(current_data_previous_study.domain) != len(domain):
                print('Erreur les domaines de la précédente étude sont différents de l espace de recherche')
                return

        for i in range(len(current_data_previous_study)):
            d = []
            for j in range(len(current_data_previous_study.domain)):
                # dernier ligne on ajoute le score renvoyé
                if i == len(current_data_previous_study) - 1 and current_data_previous_study[i][j] == '?'  and score != None:
                    d.append(score[j-len(current_data_search_space.domain)])
                else:
                    d.append(current_data_previous_study[i][j].value)

            # on ajoute les scores car self.current_data_previous_study.domain ne contient qu'un seul score à l'init pour la première étude
            if len(current_data_previous_study) == 1 and len_score is not None and len_score > 1:
                for j in range(len_score):
                    if j != 0:
                        d.append(score[j])
            data.append(d)
    return data, domain


def get_trial_params_best_params(distributions, param_score_previous_study, domain, data, name_score, len_score, stop):
    ## si l'étude est fini on ne demande pas un nouveaux jeu de params mais juste le best params
    current_proposition_out = []
    if stop == False:
        trial_params, best_params = create_study([], name_score, distributions,
                                                              param_score_previous_study, trial=True)
        ligne = []

        for j in range(len(trial_params)):
            # on ajoute au contenu_csv l'etude optuna
            for i, elem in enumerate(domain):
                if elem in trial_params[j].keys():
                    ligne.append(str(trial_params[j][elem]))
        if len_score:
            for i in range(len_score):
                ligne.append('?')
        else:
            ligne.append('?')
        current_proposition_out = [ligne]
        data = data + [ligne]

    if stop == True:
        trial_params, best_params = create_study([], name_score, distributions,
                                                              param_score_previous_study, trial=False)

    return trial_params, best_params, data, current_proposition_out

def launch_study(score, len_score, current_data_search_space, current_data_previous_study, stop):
    data, domain = get_domain_and_data_from_previous_study(score, len_score, current_data_search_space, current_data_previous_study)

    # on créé un tableau avec les domaines et données comme demandé par optuna_multi
    new_data = [domain] + data
    distributions = get_distributions(new_data)

    param_score_previous_study = []
    best_study = []

    name_score = []
    if score is None:
        name_score.append('score')
    else:
        for i in range(len_score):
            name_score.append('score' + str(i))
    # une étude minimum pour récupérer les anciennes études
    if len(new_data) > 4:
        param_score_previous_study = get_param_score_previous_study(new_data, distributions, name_score)

    trial_params, best_params, data, current_proposition_out = get_trial_params_best_params(distributions, param_score_previous_study,
                                                                        domain, data, name_score, len_score, stop)

    ligne_best_etude = []
    if best_params != []:
        for i in range(len(param_score_previous_study)):
            for j in range(len(best_params)):
                if param_score_previous_study[i]['params'] == best_params[j]['params']:
                    best_study.append(param_score_previous_study[i])
        for j in range(len(best_study)):
            l = []
            for i, elem in enumerate(domain):
                if elem in best_study[j]['params'].keys():
                    l.append(str(best_study[j]['params'][elem]))
            for i in range(len(name_score)):
                l.append(best_study[j]['scores'][i])
            ligne_best_etude.append(l)

    return ligne_best_etude, data, domain, current_proposition_out

if __name__ == "__main__":
    if len(sys.argv)!=2:
        print("erreur attendu optuna_kh fichier_csv")
        exit(1)

    filename = str(sys.argv[1]) #"optimisation_multi_objectif_ascalon.csv" #"C:\\optuna_pour_fred\\v2\\mon_fichier.csv"
    if 0!=complete_fichier_avec_proposition_optuna(filename):
        print("erreur a la completion")
        time.sleep(10)
        exit(1)
    exit(0)