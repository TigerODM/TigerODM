import os
import sys
import threading
import time
import unicodedata
import re

import Orange
from Orange.widgets.widget import Input, Output
from AnyQt.QtWidgets import QApplication, QPushButton, QLabel, QWidget, QVBoxLayout, QGroupBox
from AnyQt.QtCore import QUrl, QTimer, Signal
from Orange.widgets.settings import Setting
from AnyQt.QtWebEngineWidgets import QWebEngineView

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse, urljoin, parse_qs

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, base_widget
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert
else:
    from orangecontrib.AAIT.utils import thread_management, base_widget
    from orangecontrib.HLIT_dev.remote_server_smb import convert





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

    browser_request_signal = Signal(str, int)

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

        # UI viewer embarqué
        self.groupBox_browser = self.findChild(QGroupBox, "groupBox_browser")
        self.label_browser_status = self.findChild(QLabel, "label_browser_status")
        self.web_placeholder = self.findChild(QWidget, "web_placeholder")
        self.pushButton_browser_check = self.findChild(QPushButton, "pushButton_browser_check")
        self.pushButton_browser_close = self.findChild(QPushButton, "pushButton_browser_close")

        self.browser_view = None
        self.browser_timer = QTimer(self)
        self.browser_timer.timeout.connect(self._browser_periodic_check)

        self._browser_request_event = None
        self._browser_request_data = None
        self._browser_wait_deadline = 0.0
        self._browser_active = False
        self._browser_last_html = ""

        # Cookies du viewer Qt -> requests.Session
        self.browser_cookies = []
        self.browser_cookie_lock = threading.Lock()

        self.browser_request_signal.connect(self._open_browser_for_query)
        self._init_embedded_browser_ui()

    def _init_embedded_browser_ui(self):
        if self.groupBox_browser is not None:
            self.groupBox_browser.hide()

        if self.pushButton_browser_check is not None:
            self.pushButton_browser_check.clicked.connect(self._browser_check_current_page)

        if self.pushButton_browser_close is not None:
            self.pushButton_browser_close.clicked.connect(self._browser_cancel_request)

        if QWebEngineView is None:
            if self.label_browser_status is not None:
                self.label_browser_status.setText("QWebEngineView is not available.")
            if self.pushButton_browser_check is not None:
                self.pushButton_browser_check.setEnabled(False)
            if self.pushButton_browser_close is not None:
                self.pushButton_browser_close.setEnabled(False)
            return

        if self.web_placeholder is None:
            return

        layout = self.web_placeholder.layout()
        if layout is None:
            layout = QVBoxLayout(self.web_placeholder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

        self.browser_view = QWebEngineView(self.web_placeholder)
        layout.addWidget(self.browser_view)
        self.browser_view.hide()
        self.browser_view.loadFinished.connect(self._browser_on_load_finished)

        try:
            cookie_store = self.browser_view.page().profile().cookieStore()
            cookie_store.cookieAdded.connect(self._on_cookie_added)
        except Exception as e:
            print(f"[WARN] Impossible de brancher le cookie store Qt: {e}")

    def _on_cookie_added(self, cookie):
        try:
            name = bytes(cookie.name()).decode("utf-8", errors="ignore")
            value = bytes(cookie.value()).decode("utf-8", errors="ignore")
            domain = cookie.domain() if hasattr(cookie, "domain") else ""
            path = cookie.path() if hasattr(cookie, "path") else "/"

            item = {
                "name": name,
                "value": value,
                "domain": domain or "",
                "path": path or "/",
            }

            with self.browser_cookie_lock:
                replaced = False
                for i, existing in enumerate(self.browser_cookies):
                    if (
                        existing["name"] == item["name"]
                        and existing["domain"] == item["domain"]
                        and existing["path"] == item["path"]
                    ):
                        self.browser_cookies[i] = item
                        replaced = True
                        break
                if not replaced:
                    self.browser_cookies.append(item)
        except Exception as e:
            print(f"[WARN] _on_cookie_added error: {e}")

    def _copy_qt_cookies_to_session(self, session):
        with self.browser_cookie_lock:
            cookies_snapshot = list(self.browser_cookies)

        for c in cookies_snapshot:
            try:
                name = c.get("name", "")
                value = c.get("value", "")
                domain = c.get("domain", "")
                path = c.get("path", "/") or "/"

                if not name:
                    continue

                if domain:
                    session.cookies.set(name, value, domain=domain, path=path)
                    # variante sans le point initial éventuel
                    if domain.startswith("."):
                        session.cookies.set(name, value, domain=domain.lstrip("."), path=path)
                else:
                    session.cookies.set(name, value, path=path)
            except Exception as e:
                print(f"[WARN] copy cookie error: {e}")

    def _get_browser_user_agent(self):
        try:
            if self.browser_view is not None:
                return self.browser_view.page().profile().httpUserAgent()
        except Exception:
            pass
        return "Mozilla/5.0"

    def _is_duckduckgo_challenge(self, html):
        if not html:
            return False
        h = html.lower()
        markers = [
            "anomaly-modal",
            "bots use duckduckgo too",
            "please complete the following challenge",
            "select all squares containing",
            "challenge-form",
            "anomaly.js",
        ]
        return any(m in h for m in markers)

    def _parse_ddg_results_from_html(self, html, max_results):
        soup = BeautifulSoup(html, "html.parser")
        resultats = []

        for a in soup.select("a.result__a")[:max_results]:
            titre = a.get_text(strip=True)
            lien = a.get("href", "")

            parsed = urlparse(lien)
            if parsed.netloc and "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
                qs = parse_qs(parsed.query)
                if "uddg" in qs:
                    lien = qs["uddg"][0]

            if lien.startswith("/"):
                lien = urljoin("https://duckduckgo.com", lien)

            resultats.append((titre, lien))

        return resultats

    def _open_browser_for_query(self, query, wait_timeout):
        if self._browser_request_data is None:
            return

        if self.browser_view is None:
            self._browser_finish_request(html=None, cancelled=True, message="QWebEngineView unavailable.")
            return

        q = quote(query)
        url = f"https://duckduckgo.com/html/?q={q}"

        self._browser_active = True
        self._browser_last_html = ""
        self._browser_wait_deadline = time.time() + wait_timeout

        if self.groupBox_browser is not None:
            self.groupBox_browser.show()

        if self.label_browser_status is not None:
            self.label_browser_status.setText(
                "Captcha detected.\n"
                "Solve it in the embedded browser."
            )

        self.browser_view.show()
        self.browser_view.setUrl(QUrl(url))
        self.browser_timer.start(2000)

    def _browser_on_load_finished(self, ok):
        if not self._browser_active:
            return
        if not ok:
            if self.label_browser_status is not None:
                self.label_browser_status.setText("DuckDuckGo load error.")
            return
        self._browser_check_current_page()

    def _browser_periodic_check(self):
        if not self._browser_active:
            self.browser_timer.stop()
            return

        if time.time() >= self._browser_wait_deadline:
            self._browser_finish_request(html=None, cancelled=True, message="Captcha timeout.")
            return

        self._browser_check_current_page()

    def _browser_check_current_page(self):
        if not self._browser_active or self.browser_view is None:
            return

        try:
            page = self.browser_view.page()
            if page is None:
                return
            page.toHtml(self._browser_process_html)
        except Exception as e:
            if self.label_browser_status is not None:
                self.label_browser_status.setText(f"Check error: {e}")

    def _browser_process_html(self, html):
        if not self._browser_active:
            return

        html = html or ""
        self._browser_last_html = html

        if self._is_duckduckgo_challenge(html):
            if self.label_browser_status is not None:
                self.label_browser_status.setText(
                    "Captcha still present.\n"
                    "Solve it, then wait for automatic detection."
                )
            return

        if self.label_browser_status is not None:
            self.label_browser_status.setText("Results detected.")

        self._browser_finish_request(html=html, cancelled=False, message=None)

    def _browser_cancel_request(self):
        self._browser_finish_request(html=None, cancelled=True, message="Validation cancelled.")

    def _browser_finish_request(self, html=None, cancelled=False, message=None):
        self.browser_timer.stop()
        self._browser_active = False

        if self.browser_view is not None:
            try:
                self.browser_view.stop()
            except Exception:
                pass
            try:
                self.browser_view.setUrl(QUrl("about:blank"))
            except Exception:
                pass
            self.browser_view.hide()

        if self.groupBox_browser is not None:
            self.groupBox_browser.hide()

        if self.label_browser_status is not None:
            if message:
                self.label_browser_status.setText(message)
            else:
                self.label_browser_status.setText(
                    "The embedded browser will appear here only if manual validation is needed."
                )

        if self._browser_request_data is not None:
            self._browser_request_data["html"] = html
            self._browser_request_data["cancelled"] = cancelled

        if self._browser_request_event is not None:
            self._browser_request_event.set()

    def normaliser_texte(self, txt: str) -> str:
        """
        Met en minuscules, retire les accents et trim.
        """
        if not txt:
            return ""
        txt = txt.lower()
        txt = unicodedata.normalize("NFD", txt)
        txt = "".join(c for c in txt if not unicodedata.combining(c))
        return txt.strip()

    def extraire_mots_cles(self, requete: str):
        """
        Découpe la requête en mots-clés simples, en retirant
        les mots très fréquents (du, de, le, la, etc.).
        """
        stopwords = {"du", "de", "des", "le", "la", "les", "un", "une", "au", "aux", "et", "en", "pour", "sur", "a"}
        req_norm = self.normaliser_texte(requete)
        mots = re.findall(r"\w+", req_norm)
        mots_cles = [m for m in mots if m not in stopwords and len(m) > 2]
        return mots_cles or mots

    def recherche_duckduckgo(self, query, max_results=10):
        q = quote(query)
        url = f"https://duckduckgo.com/html/?q={q}"

        session = requests.Session()
        headers = {
            "User-Agent": self._get_browser_user_agent(),
            # "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            # "Referer": "https://duckduckgo.com/",
        }

        def do_request():
            r = session.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            return r.text

        try:
            r = session.get(url, headers=headers, timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[ERREUR] Problème lors de la requête DuckDuckGo : {e}")
            return []

        html = r.text

        # Cas normal = ton code d'origine
        if not self._is_duckduckgo_challenge(html):
            return self._parse_ddg_results_from_html(html, max_results)

        # Cas captcha = viewer Qt
        print("[INFO] Challenge DuckDuckGo détecté.")
        print("[INFO] Ouverture du navigateur embarqué pour résolution manuelle...")

        if QWebEngineView is None or self.browser_view is None:
            print("[ERREUR] QWebEngineView non disponible.")
            return []

        wait_event = threading.Event()
        request_data = {
            "html": None,
            "cancelled": False,
        }

        self._browser_request_event = wait_event
        self._browser_request_data = request_data

        self.browser_request_signal.emit(query, 120)
        wait_event.wait(125)

        data = self._browser_request_data
        self._browser_request_event = None
        self._browser_request_data = None

        if not data or data.get("cancelled"):
            print("[ERREUR] Validation DuckDuckGo annulée ou timeout.")
            return []

        viewer_html = data.get("html") or ""
        if not viewer_html:
            print("[ERREUR] HTML vide après validation.")
            return []

        if self._is_duckduckgo_challenge(viewer_html):
            print("[ERREUR] Captcha toujours présent après validation.")
            return []

        # On copie les cookies Qt -> requests.Session
        self._copy_qt_cookies_to_session(session)

        # 1) on tente de relancer requests avec les mêmes cookies
        try:
            html_after = do_request()
            if not self._is_duckduckgo_challenge(html_after):
                resultats = self._parse_ddg_results_from_html(html_after, max_results)
                if resultats:
                    return resultats
        except requests.RequestException as e:
            print(f"[WARN] Requête requests après synchro cookies en échec: {e}")

        # 2) fallback: on parse directement le HTML du viewer
        resultats = self._parse_ddg_results_from_html(viewer_html, max_results)
        if resultats:
            return resultats

        print("[ERREUR] Aucun résultat parsable après validation captcha.")
        return []

    def extraire_domaines(self, resultats_search):
        domaines = set()
        for _titre, url in resultats_search:
            try:
                parsed = urlparse(url)
                scheme = parsed.scheme or "https"
                if not parsed.netloc:
                    continue
                domaine = f"{scheme}://{parsed.netloc}"
                domaines.add(domaine)
            except Exception:
                pass
        return list(domaines)

    def trouver_flux_rss(self, url_site):
        try:
            r = requests.get(url_site, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[ERREUR] Impossible d'accéder à {url_site} : {e}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        flux = []

        for link in soup.find_all("link", type="application/rss+xml"):
            href = link.get("href")
            if href:
                href = urljoin(url_site, href)
                flux.append(href)

        for link in soup.find_all("a"):
            href = link.get("href", "")
            if not href:
                continue
            href_norm = href.lower()
            if "rss" in href_norm or "feed" in href_norm:
                flux.append(urljoin(url_site, href))

        return list(set(flux))

    def rechercher_articles_dans_flux(self, requete, flux_list, max_results=20):
        mots_cles = self.extraire_mots_cles(requete)
        articles = []

        headers = {"User-Agent": "Mozilla/5.0"}

        for flux in flux_list:
            try:
                r = requests.get(flux, headers=headers, timeout=10)
                r.raise_for_status()
                # Parse du flux en XML
                soup = BeautifulSoup(r.content, "xml")
            except requests.RequestException as e:
                print(f"[ERREUR] Problème lors de la lecture du flux {flux} : {e}")
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
                    # Atom : <link href="...">
                    if lien_tag.has_attr("href"):
                        lien = lien_tag["href"]
                    else:
                        # RSS : <link>https://...</link>
                        lien = lien_tag.get_text(strip=True)

                # Date
                date_tag = (
                        entry.find("pubDate")
                        or entry.find("published")
                        or entry.find("updated")
                )
                date = date_tag.get_text(strip=True) if date_tag else "Date inconnue"

                texte_complet = self.normaliser_texte(titre + " " + resume)

                # Condition : au moins un mot-clé présent dans titre+résumé
                if any(mot in texte_complet for mot in mots_cles):
                    articles.append(
                        {
                            "titre": titre,
                            "url": lien,
                            "date": date,
                            "source_flux": flux,
                        }
                    )
                    if len(articles) >= max_results:
                        return articles

        return articles

    def pipeline_veille_requete(self, requete):
        resultats = self.recherche_duckduckgo(requete)
        if not resultats:
            print("Aucun résultat trouvé sur DuckDuckGo.")
            return []
        print(resultats)
        domaines = self.extraire_domaines(resultats)

        flux = []
        for d in domaines:
            found = self.trouver_flux_rss(d)
            if found:
                print(f"Flux trouvés sur {d}:")
                for f in found:
                    print(" ->", f)
                flux.extend(found)

        flux = list(set(flux))

        if not flux:
            return [
                {"titre": t, "url": u, "date": None, "source_flux": None, "source": "web"}
                for t, u in resultats
            ]

        articles = self.rechercher_articles_dans_flux(requete, flux)

        if not articles:
            return [
                {"titre": t, "url": u, "date": None, "source_flux": None, "source": "web"}
                for t, u in resultats
            ]
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