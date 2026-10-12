import os
import sys
import unicodedata
import re
import warnings
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import Orange
from Orange.widgets.widget import Input, Output
from AnyQt.QtWidgets import QApplication, QPushButton
from Orange.widgets.settings import Setting

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, base_widget
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert
else:
    from orangecontrib.AAIT.utils import thread_management, base_widget
    from orangecontrib.HLIT_dev.remote_server_smb import convert

JOURS_MAX_ANCIENNETE = 90

DOMAINES_BLACKLIST = {
    "jeretiens.net", "wikipedia.org", "wikimedia.org",
    "larousse.fr", "linternaute.fr", "futura-sciences.com",
    "maxicours.com", "kartable.fr",
    "marmiton.org", "750g.com", "cuisineaz.com",
    "chefsimon.com", "croq-kilos.com", "laterrassesaintvalery.fr",
    "leboncoin.fr", "seloger.com", "pagesjaunes.fr", "lacentrale.fr",
    "reddit.com", "quora.com", "commentcamarche.net",
    "aufeminin.com", "doctissimo.fr", "santeplus.fr",
    "inc-conso.fr", "madeinfr.fr",
}

PATTERNS_URL_BLACKLIST = [
    r"/recette", r"/cuisine", r"/sante", r"/beaute",
    r"/loisir", r"/divertissement", r"/culture-generale", r"/geographie",
    r"comment-page", r"#comment-",
    r"/mentions?-legales?", r"/legal", r"/cgu", r"/cgv",
    r"/privacy", r"/politique-de-confidentialite",
    r"/contact", r"/a-propos", r"/about",
]


class WebSearch(base_widget.BaseListWidget):
    name = "WebSearch"
    description = "Search url website from a query with DDG."
    icon = "icons/websearch.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/websearch.png"
    priority = 3000
    gui = ""
    want_control_area = False
    category = "AAIT - TOOLBOX"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owwebsearch.ui")

    selected_column_name = Setting("content")
    jours_max = Setting(JOURS_MAX_ANCIENNETE)   # configurable via UI

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if in_data is None:
            self.Outputs.data.send(None)
            return
        if self.data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        self.run()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(480)
        self.setFixedHeight(760)
        self.pushButton_run = self.findChild(QPushButton, 'pushButton_send')
        self.pushButton_run.clicked.connect(self.run)

    def normaliser_texte(self, txt: str) -> str:
        if not txt:
            return ""
        txt = txt.lower()
        txt = unicodedata.normalize("NFD", txt)
        txt = "".join(c for c in txt if not unicodedata.combining(c))
        return txt.strip()

    def extraire_mots_cles(self, requete: str) -> list:
        stopwords = {
            "du", "de", "des", "le", "la", "les", "un", "une", "au", "aux",
            "et", "en", "pour", "sur", "a", "par", "avec", "dans", "est",
            "prix", "cours", "cotation", "marche", "tarif", "cout", "semaine",
            "actuel", "actualite", "tendance", "hausse", "baisse", "evolution",
        }
        req_norm = self.normaliser_texte(requete)
        mots = re.findall(r"\w+", req_norm)
        return [m for m in mots if m not in stopwords and len(m) > 2] or mots

    def extraire_mots_produit(self, requete: str) -> list:
        stopwords_larges = {
            "du", "de", "des", "le", "la", "les", "un", "une", "au", "aux",
            "et", "en", "pour", "sur", "a", "par", "avec", "dans", "est",
            "prix", "cours", "cotation", "marche", "tarif", "cout", "semaine",
            "actuel", "actualite", "tendance", "hausse", "baisse", "evolution",
            "france", "europe", "mondial", "international", "national",
            "mai", "juin", "juillet", "aout", "septembre", "octobre",
            "novembre", "decembre", "janvier", "fevrier", "mars", "avril",
            "2024", "2025", "2026", "2027",
        }
        req_norm = self.normaliser_texte(requete)
        mots = re.findall(r"\w+", req_norm)
        return [m for m in mots if m not in stopwords_larges and len(m) > 2]

    def parser_date(self, date_str: str):
        """
        Tente de parser une date RSS/Atom en datetime aware (UTC).
        Supporte : RFC 2822 (RSS), ISO 8601 (Atom), et quelques variantes.
        Retourne None si impossible à parser.
        """
        if not date_str or date_str == "Date inconnue":
            return None
        # Nettoyage basique
        date_str = date_str.strip()
        # Tentative RFC 2822 (format RSS standard)
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            pass
        # Tentative ISO 8601 / Atom
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                continue
        return None

    def est_recent(self, date_str: str) -> bool:
        """
        Retourne True si l'article date de moins de self.jours_max jours.
        Retourne True aussi si la date est absente (on ne rejette pas faute d'info).
        """
        dt = self.parser_date(date_str)
        if dt is None:
            return True  # pas de date → on garde par défaut
        limite = datetime.now(tz=timezone.utc) - timedelta(days=self.jours_max)
        return dt >= limite

    def est_url_valide(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower().lstrip("www.")
            for domaine in DOMAINES_BLACKLIST:
                if netloc == domaine or netloc.endswith("." + domaine):
                    return False
            url_lower = url.lower()
            for pattern in PATTERNS_URL_BLACKLIST:
                if re.search(pattern, url_lower):
                    return False
        except Exception:
            return False
        return True

    def normaliser_url(self, url: str) -> str:
        try:
            return urlparse(url)._replace(fragment="").geturl()
        except Exception:
            return url

    def score_pertinence(self, texte: str, mots_produit: list) -> int:
        texte_norm = self.normaliser_texte(texte)
        return sum(1 for mot in mots_produit if mot in texte_norm)

    def est_pertinent(self, texte: str, mots_produit: list) -> tuple:
        if not mots_produit:
            return True, 1
        score = self.score_pertinence(texte, mots_produit)
        return score >= len(mots_produit), score

    def filtrer_et_trier(self, resultats: list, mots_produit: list) -> list:
        scores = []
        for r in resultats:
            texte = r.get("titre", "") + " " + r.get("resume", "") + " " + r.get("url", "")
            ok, score = self.est_pertinent(texte, mots_produit)
            if ok:
                scores.append((score, r))
        scores.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scores]

    def generer_variantes(self, requete: str) -> list:
        mots_cles = self.extraire_mots_cles(requete)
        base = " ".join(mots_cles)
        variantes = [
            requete,
            base + " cotation marché",
            base + " prix semaine actualité",
        ]
        return list(dict.fromkeys(variantes))

    def recherche_duckduckgo(self, query, max_results=10):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with DDGS() as ddgs:
                    results = list(ddgs.text(
                        query,
                        max_results=max_results,
                        region="fr-fr",
                        safesearch="off",
                    ))
            return [{"titre": r["title"], "url": r["href"], "resume": r.get("body", "")} for r in results] if results else []
        except Exception as e:
            self.thread.progress.emit((None, f"[ERREUR DDG] {e}\n"))
            return []

    def recherche_multi_variantes(self, requete: str, mots_produit: list) -> list:
        variantes = self.generer_variantes(requete)
        tous_resultats = {}
        for v in variantes:
            self.thread.progress.emit((None, f"  → DDG : {v}\n"))
            res = self.recherche_duckduckgo(v, max_results=10)
            for r in res:
                url_norm = self.normaliser_url(r["url"])
                if not self.est_url_valide(url_norm):
                    continue
                if url_norm not in tous_resultats:
                    r["url"] = url_norm
                    tous_resultats[url_norm] = r

        bruts = list(tous_resultats.values())
        filtres = self.filtrer_et_trier(bruts, mots_produit)
        self.thread.progress.emit((None, f"  {len(filtres)} gardés / {len(bruts)-len(filtres)} hors-sujet\n"))
        return filtres

    def extraire_domaines(self, resultats):
        domaines = set()
        for r in resultats:
            try:
                parsed = urlparse(r["url"])
                if parsed.netloc:
                    domaines.add(f"{parsed.scheme or 'https'}://{parsed.netloc}")
            except Exception:
                pass
        return list(domaines)

    def trouver_flux_rss(self, url_site):
        try:
            r = requests.get(url_site, headers={"User-Agent": "Mozilla/5.0"}, timeout=10, verify=False)
            r.raise_for_status()
        except requests.RequestException as e:
            self.thread.progress.emit((None, f"[ERREUR RSS] {url_site} : {e}\n"))
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        flux = []

        for link in soup.find_all("link", type="application/rss+xml"):
            href = link.get("href")
            if href:
                flux.append(urljoin(url_site, href))
        for link in soup.find_all("a"):
            href = link.get("href", "")
            if href and ("rss" in href.lower() or "feed" in href.lower()):
                flux.append(urljoin(url_site, href))
        return list(set(flux))

    def rechercher_articles_dans_flux(self, flux_list, mots_produit, max_results=20):
        articles = []
        vus = set()
        rejetes_date = 0
        headers = {"User-Agent": "Mozilla/5.0"}

        for flux in flux_list:
            try:
                r = requests.get(flux, headers=headers, timeout=10, verify=False)
                r.raise_for_status()
                soup = BeautifulSoup(r.content, "xml")
            except requests.RequestException as e:
                self.thread.progress.emit((None, f"[ERREUR flux] {flux} : {e}\n"))
                continue

            # Gestion RSS (<item>) et Atom (<entry>)
            for entry in soup.find_all(["item", "entry"]):
                # Titre
                titre_tag = entry.find("title")
                titre = titre_tag.get_text(strip=True) if titre_tag else ""

                # Résumé / description
                resume_tag = entry.find("description") or entry.find("summary")
                resume = resume_tag.get_text(strip=True) if resume_tag else ""

                # Lien
                lien_tag = entry.find("link")
                lien = ""
                if lien_tag:
                    lien = lien_tag["href"] if lien_tag.has_attr("href") else lien_tag.get_text(strip=True)

                lien_norm = self.normaliser_url(lien)

                if not self.est_url_valide(lien_norm) or lien_norm in vus:
                    continue
                vus.add(lien_norm)

                date_tag = entry.find("pubDate") or entry.find("published") or entry.find("updated")
                date = date_tag.get_text(strip=True) if date_tag else "Date inconnue"

                # ← FILTRE DATE ICI
                if not self.est_recent(date):
                    rejetes_date += 1
                    continue

                ok, score = self.est_pertinent(titre + " " + resume, mots_produit)
                if ok:
                    articles.append({
                        "titre": titre,
                        "url": lien_norm,
                        "date": date,
                        "source_flux": flux,
                        "resume": resume,
                        "score": score,
                    })
                    if len(articles) >= max_results:
                        break

        if rejetes_date > 0:
            self.thread.progress.emit((None, f"  {rejetes_date} articles trop anciens (>{self.jours_max}j) ignorés\n"))

        articles.sort(key=lambda x: x["score"], reverse=True)
        return articles

    def pipeline_veille_requete(self, requete):
        mots_produit = self.extraire_mots_produit(requete)
        self.thread.progress.emit((10, f"Produit ciblé : {mots_produit}\n"))
        self.thread.progress.emit((10, f"Fenêtre temporelle : {self.jours_max} jours\n"))

        resultats = self.recherche_multi_variantes(requete, mots_produit)
        if not resultats:
            self.thread.progress.emit((50, "Aucun résultat pertinent.\n"))
            return []

        self.thread.progress.emit((40, f"{len(resultats)} résultats — recherche RSS...\n"))

        domaines = self.extraire_domaines(resultats)
        flux = []
        for d in domaines:
            found = self.trouver_flux_rss(d)
            if found:
                self.thread.progress.emit((None, f"  RSS : {d}\n"))
                flux.extend(found)
        flux = list(set(flux))
        self.thread.progress.emit((70, f"{len(flux)} flux RSS\n"))

        if not flux:
            self.thread.progress.emit((100, "Pas de RSS — résultats DDG retournés.\n"))
            return [{"titre": r["titre"], "url": r["url"], "date": None, "source_flux": None, "source": "web", "resume": r.get("resume", "")} for r in resultats]

        articles = self.rechercher_articles_dans_flux(flux, mots_produit)

        if not articles:
            self.thread.progress.emit((100, f"Aucun article récent (<{self.jours_max}j) — fallback DDG.\n"))
            return [{"titre": r["titre"], "url": r["url"], "date": None, "source_flux": None, "source": "web", "resume": r.get("resume", "")} for r in resultats]

        self.thread.progress.emit((100, f"Terminé — {len(articles)} articles récents.\n"))
        return articles

    def run(self):
        self.error("")
        self.warning("")
        if self.data is None:
            self.Outputs.data.send(None)
            return

        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            return

        self.query = self.data.get_column(self.selected_column_name)[0]

        self.progressBarInit()
        self.thread = thread_management.Thread(self.pipeline_veille_requete, self.query)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, progress) -> None:
        value = progress[0]
        text = progress[1]
        if value is not None:
            self.progressBarSet(value)
        if hasattr(self, "textBrowser"):
            if text is None:
                self.textBrowser.setText("")
            else:
                self.textBrowser.insertPlainText(text)

    def handle_result(self, result):
        if result is None or len(result) == 0:
            self.Outputs.data.send(None)
            return
        data = convert.convert_json_implicite_to_data_table(result)
        self.Outputs.data.send(data)

    def handle_finish(self):
        self.progressBarFinished()

    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = WebSearch()
    my_widget.show()
    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())