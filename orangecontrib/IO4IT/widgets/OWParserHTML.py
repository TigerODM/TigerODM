import os
import sys
import Orange
from Orange.widgets.widget import OWWidget, Input, Output
from AnyQt.QtWidgets import QApplication
import asyncio
import html2text
from bs4 import BeautifulSoup
import urllib.request
import urllib3
import requests
from requests_ntlm import HttpNtlmAuth

# Désactive les avertissements SSL pour certificats d'entreprise auto-signés
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.HLIT_dev.remote_server_smb import convert
    from orangecontrib.AAIT.utils import thread_management

class ParseHMTL(OWWidget):
    name = "ParseHTML"
    description = "Parse website HTML. You need to provide url(s) in input."
    icon = "icons/html.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/html.png"
    priority = 3000
    want_control_area = False
    category = "AAIT - TOOLBOX"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owparserhtml.ui")

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(500)
        self.setFixedHeight(400)
        uic.loadUi(self.gui, self)

        self.data = None
        self.url_data = []
        self.thread = None
        self.markdown = True
        self.proxy_url = self._get_enterprise_proxy_url()
        self.ntlm_auth = HttpNtlmAuth('', '')
        self.run()

    def update_parameters(self):
        return



    @Inputs.data
    def set_data(self, in_data):
        if in_data is None:
            return
        if "url" not in in_data.domain:
            self.error("input table need a url column")
            return
        self.data = in_data
        self.url_data = list(in_data.get_column("url"))
        self.run()

    def _get_enterprise_proxy_url(self):
        proxies_dict = urllib.request.getproxies()
        raw_proxy = proxies_dict.get("http") or proxies_dict.get("https")
        if raw_proxy and not raw_proxy.startswith("http"):
            return f"http://{raw_proxy}"
        return raw_proxy

    def _sync_fetch(self, url: str) -> str:
        """
        Appel réseau réel (synchrone) compatible NTLM, exécuté dans un thread via run_in_executor.
        """
        session = requests.Session()
        session.verify = False  # ignore certifs d'entreprise

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

        proxies = None
        if self.proxy_url:
            proxies = {"http": self.proxy_url, "https": self.proxy_url}

        resp = session.get(
            url,
            proxies=proxies,
            auth=self.ntlm_auth,
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return resp.text

    def parse_html(self):
        """Execute le parsing"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(self.parse_all_urls(progress_callback=self._progress_cb))
            loop.close()
            return results
        except Exception as e:
            self.error(str(e))
            return

    def _progress_cb(self, value: int, text: str = None):
        """
        Callback interne utilisé par parse_all_urls.
        On renvoie un tuple (value, text) au thread Qt, comme ton handle_progress s'y attend.
        """
        if self.thread is not None:
            self.thread.progress.emit((value, text))

    async def parse_all_urls(self, progress_callback=None):
        """
        Parse toutes les URLs en concurrence (comme dans le 2e code) en gardant une progression fluide.
        """
        results = []
        total = len(self.url_data)
        if total == 0:
            return results

        tasks = [self.parse_single_url(url) for url in self.url_data]

        for i, task in enumerate(asyncio.as_completed(tasks)):
            result = await task
            results.append(result)

            if progress_callback:
                progress_value = int(((i + 1) / total) * 100)
                progress_callback(progress_value, None)

        return results

    async def parse_single_url(self, url: str):
        """
        Appel sync (requests+ntlm) dans executor, puis parsing BeautifulSoup + extraction contenu.
        """
        try:
            loop = asyncio.get_event_loop()
            html = await loop.run_in_executor(None, self._sync_fetch, url)

            soup = BeautifulSoup(html, 'html.parser')
            meta_desc = ''
            meta_tag = soup.find('meta', attrs={'name': 'description'})
            if not meta_tag:
                meta_tag = soup.find('meta', property='og:description')
            if meta_tag:
                meta_desc = meta_tag.get('content', '')

            try:
                content = self._extract_main_content(soup)
            except Exception:
                content = ''

            word_count = len(content.split()) if content else 0

            return {
                "url": url,
                "content": content,
                "meta_description": meta_desc,
                "word_count": word_count,
                "status": "success"
            }

        except Exception as e:
            return {
                "url": url,
                "content": "",
                "meta_description": "",
                "word_count": 0,
                "status": f"error: {str(e)}"
            }

    def _extract_main_content(self, soup):
        """Extrait le contenu principal et le convertit en Markdown"""
        main_selectors = [
            'article',
            'main',
            '[role="main"]',
            '.content',
            '.main-content',
            '#content',
            '.article-body',
            '.post-content'
        ]
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = False
        converter.body_width = 0
        for selector in main_selectors:
            main_elem = soup.select_one(selector)
            if main_elem:
                if self.markdown:
                    html = str(main_elem)
                    markdown = converter.handle(html)
                    if len(markdown.split()) > 100:
                        return markdown.strip()
                else:
                    paragraphs = main_elem.find_all('p')
                    if paragraphs:
                        text = ' '.join([p.get_text(strip=True) for p in paragraphs])
                        if len(text) > 100:
                            return text
        paragraphs = soup.find_all('p')
        if paragraphs:
            return ' '.join([p.get_text(strip=True) for p in paragraphs])

        return soup.get_text(strip=True, separator=' ')

    def run(self):
        self.error("")
        self.warning("")
        if self.data is None:
            self.Outputs.data.send(None)
            return
        self.progressBarInit()
        self.thread = thread_management.Thread(self.parse_html)
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
        data = convert.convert_json_implicite_to_data_table(result)
        self.Outputs.data.send(data)
        self.data = None

    def handle_finish(self):
        print("Generation finished")
        self.progressBarFinished()

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = ParseHMTL()
    my_widget.show()

    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
