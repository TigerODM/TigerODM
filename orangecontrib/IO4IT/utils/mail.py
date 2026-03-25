import imaplib
import smtplib
import email
from email.header import decode_header
import time
import os
from email import policy
from email.message import EmailMessage
import mimetypes

from exchangelib import Credentials, HTMLBody, Message, Mailbox
#from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
from exchangelib import OAuth2Credentials, Identity, Configuration, Account, DELEGATE
import requests
import base64
from bs4 import BeautifulSoup


##### please uncomment this line to ignore certificate checking (owa)
#BaseProtocol.HTTP_ADAPTER_CLS=NoVerifyHTTPAdapter

from msal import ConfidentialClientApplication
from oauthlib.oauth2 import OAuth2Token

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
    from Orange.widgets.orangecontrib.IO4IT.utils import keys_manager
else:
    from orangecontrib.AAIT.utils import MetManagement
    from orangecontrib.IO4IT.utils import keys_manager


def clean_addresses(field,myemail):
    """Retourne une liste d'adresses nettoyées sans ton adresse"""
    if not field:
        return []
    addresses = email.utils.getaddresses([field])
    return [addr for name, addr in addresses if addr.lower() != myemail.lower()]

def mail_in_folder(agent_name, type="in"):
    if agent_name is None or agent_name == "":
        print("agent_name doit etre renseigné")
        return None
    chemin_dossier= MetManagement.get_path_mailFolder()
    if type == "in":
        if not os.path.exists(chemin_dossier):
            os.makedirs(chemin_dossier)
        real_time = MetManagement.get_second_from_1970()
        folder_in = chemin_dossier + "/" + str(agent_name) + "/in/" + str(real_time)
        folder_out = chemin_dossier + "/" + str(agent_name) + "/out/" + str(real_time)
        if not os.path.exists(folder_in) and not os.path.exists(folder_out):
            os.makedirs(folder_in)
            os.makedirs(folder_out)
        else:
            time.sleep(1.5)
            mail_in_folder(agent_name, "in")
        return folder_in
    if  type == "out":
        return chemin_dossier + str(agent_name) + "/in/", chemin_dossier + "/" + str(agent_name) + "/out/"


def mark_as_read(item):
    try:
        if not hasattr(item, "is_read"):
            print(f"Pas de is_read sur {type(item).__name__}")
            return False

        item.is_read = True
        item.save(update_fields=["is_read"])
        return True

    except Exception as e:
        print(f"Impossible de marquer comme lu ({type(item).__name__}) : {e}")
        return False


def check_new_emails(offusc_conf_agent,type_co, list_agent_email=[]):
    if type_co=="IMAP4_SSL":
        try:
            agent,my_domain,password,interl_seconds,alias=keys_manager.lire_config_imap4_ssl(offusc_conf_agent)
            myemail=agent + my_domain
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(myemail, password)
            imap.select("inbox")
            status, messages = imap.search(None, 'UNSEEN')
            mail_ids = messages[0].split()
            if not mail_ids:
                print("Aucun nouveau mail.")
            else:
                for mail_id in mail_ids:
                    if list_agent_email != []:
                        white_list, black_list = keys_manager.lire_list_email(list_agent_email)
                    else:
                        white_list=[]
                        black_list=[]
                    time.sleep(1.5)
                    output_lines = []
                    _, msg_data = imap.fetch(mail_id, '(BODY.PEEK[])')
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            from email.parser import BytesParser

                            # Utilise :
                            msg = BytesParser(policy=policy.default).parsebytes(response_part[1])

                            # Sujet
                            subject, encoding = decode_header(msg["Subject"])[0]
                            if isinstance(subject, bytes):
                                subject = subject.decode(encoding if encoding else "utf-8")

                            # Expéditeur
                            from_ = msg.get("From")
                            # Destinataires
                            to_emails = clean_addresses(msg.get("To", ""),myemail)
                            cc_emails = clean_addresses(msg.get("Cc", ""),myemail)
                            if (to_emails != [] or cc_emails != []) and alias == "":
                                if myemail not in to_emails or myemail not in cc_emails:
                                    print(f"l'adresse de reception est un alias : {to_emails}")
                                    continue
                            if (to_emails == [] and cc_emails == []) and alias != "":
                                print(f"l'adresse de reception est un alias : {alias}")
                                continue
                            ## passe en lu si ce n'est pas un alias
                            imap.store(mail_id, '+FLAGS', '\\Seen')
                            # Corps
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    content_type = part.get_content_type()
                                    content_disposition = str(part.get("Content-Disposition"))

                                    if content_type == "text/plain" and "attachment" not in content_disposition:
                                        payload = part.get_payload(decode=True)
                                        charset = part.get_content_charset()
                                        body = payload.decode(charset if charset else "utf-8", errors="replace")
                                        break
                                    elif content_type == "text/html" and "attachment" not in content_disposition:
                                        html_body = part.get_content()
                                        soup = BeautifulSoup(html_body, "html.parser")

                                        # Remove signatures or footers by rule
                                        for block in soup.find_all(["footer", "style", "script"]):
                                            block.decompose()

                                        body = soup.get_text(separator="\n", strip=True)


                            else:
                                body = msg.get_payload(decode=True).decode(errors="replace")
                            if alias != "":
                                agent = alias


                            folder = mail_in_folder(agent, "in")
                            if folder is None:
                                print("erreur dans le folder de mail")
                                return
                            ignored_pj=""
                            for part in msg.iter_attachments():
                                filename = part.get_filename()
                                if filename:
                                    if len(filename)<5:
                                        continue
                                    if not (filename.endswith(".pdf") or filename.endswith(".docx")):
                                        if ignored_pj!="":
                                            ignored_pj+=";"
                                        ignored_pj+=filename
                                        continue  # Fichier ignoré

                                    folder_pj = folder + "/" + "pj"
                                    if not os.path.exists(folder_pj):
                                        os.makedirs(folder_pj)
                                    filepath = os.path.join(folder_pj, filename)
                                    with open(filepath, "wb") as f:
                                        f.write(part.get_payload(decode=True))
                                    f.close()

                            # Format de sortie
                            output_lines.append(f"#$who : {myemail}")
                            output_lines.append(f"#$eme : {from_}")
                            output_lines.append(f"#$des : {', '.join(to_emails)}")
                            output_lines.append(f"#$cop : {', '.join(cc_emails)}")
                            output_lines.append("#$pri : Normale")
                            output_lines.append(f"#$tit : {subject}")
                            output_lines.append(f"#$ipj : {ignored_pj}")
                            output_lines.append(f"#$txt : {body.strip()}")
                            output_lines.append("")
                            print("----------------------------------------")
                            print(f"mail recu de {from_}")
                            print("----------------------------------------")
                            if white_list != [] and from_ not in white_list:
                                print("cette adresse n'est pas dans la white list")
                                continue
                            if black_list != [] and from_ in black_list:
                                print("cette adresse est dans la black list")
                                continue
                            if output_lines != []:
                                with open(folder + "/" + "mail.txt", "w", encoding="utf-8") as f:
                                    f.write("\n".join(output_lines))
                                    f.close()

                                with open(folder + "/" + "mail.ok", "w") as f:
                                    f.close()



            imap.logout()
        except Exception as e:
            print(f"Erreur lors de la vérification des mails : {e}")
    elif type_co=="MICROSOFT_EXCHANGE_OWA":
        try:
            mail, alias, server, username, password, interval_second = keys_manager.lire_config_owa(
                offusc_conf_agent)
            credentials = Credentials(username=username, password=password)
            config = Configuration(
                server=server,
                credentials=credentials,
            )

            account = Account(
                primary_smtp_address=alias,
                credentials=credentials,
                config=config,
                autodiscover=False,
                access_type=DELEGATE
            )

            # Inbox
            inbox = account.inbox.filter(is_read=False)

            if not inbox:
                print("Aucun nouveau mail.")
            else:
                for item in inbox.order_by('datetime_received'):
                    if list_agent_email != []:
                        white_list, black_list = keys_manager.lire_list_email(list_agent_email)
                    else:
                        white_list, black_list = [], []

                    # Marquer comme lu
                    mark_as_read(item)

                    if not isinstance(item,Message):
                        print('mail non standard (reunion etc...), ignore')
                        continue
                    time.sleep(1.5)
                    output_lines = []

                    from_ = item.sender.email_address
                    subject = item.subject or "(Sans sujet)"
                    to_emails = [rec.email_address for rec in item.to_recipients or []]
                    cc_emails = [rec.email_address for rec in item.cc_recipients or []]

                    if (to_emails or cc_emails) and alias == "":
                        if mail not in to_emails and mail not in cc_emails:
                            print(f"L'adresse de réception est un alias : {to_emails}")
                            continue
                    if not to_emails and not cc_emails and alias != "":
                        print(f"L'adresse de réception est un alias : {alias}")
                        continue

                    # Corps du mail
                    body = ""
                    if item.body.body_type == "HTML":
                        soup = BeautifulSoup(item.body, "html.parser")
                        for block in soup.find_all(["footer", "style", "script"]):
                            block.decompose()
                        body = soup.get_text(separator="\n", strip=True)
                    else:
                        body = item.body.strip()

                    if alias != "":
                        agent = alias

                    folder = mail_in_folder(agent, "in")
                    if folder is None:
                        print("Erreur dans le folder de mail")
                        continue

                    ignored_pj = ""
                    for attachment in item.attachments:
                        if not hasattr(attachment, 'name') or len(attachment.name) < 5:
                            continue
                        if not (attachment.name.endswith(".pdf") or attachment.name.endswith(".docx")):
                            if ignored_pj:
                                ignored_pj += ";"
                            ignored_pj += attachment.name
                            continue

                        folder_pj = os.path.join(folder, "pj")
                        os.makedirs(folder_pj, exist_ok=True)
                        filepath = os.path.join(folder_pj, attachment.name)
                        with open(filepath, "wb") as f:
                            f.write(attachment.content)

                    # Format sortie
                    output_lines.append(f"#$who : {mail}")
                    output_lines.append(f"#$eme : {from_}")
                    output_lines.append(f"#$des : {', '.join(to_emails)}")
                    output_lines.append(f"#$cop : {', '.join(cc_emails)}")
                    output_lines.append("#$pri : Normale")
                    output_lines.append(f"#$tit : {subject}")
                    output_lines.append(f"#$ipj : {ignored_pj}")
                    output_lines.append(f"#$txt : {body.strip()}")

                    # à discuter pour conversation id utile chez N pour RAG
                    # conv_id = getattr(item, "conversation_id", None)
                    # if conv_id:
                    #     conv_id_str = getattr(conv_id, "id", None) or str(conv_id)
                    #     output_lines.append(f"#$cid : {conv_id_str}

                    output_lines.append("")

                    print("----------------------------------------")
                    print(f"Mail reçu de {from_}")
                    print("----------------------------------------")

                    if white_list and from_ not in white_list:
                        print("Cette adresse n'est pas dans la white list")
                        continue
                    if black_list and from_ in black_list:
                        print("Cette adresse est dans la black list")
                        continue

                    with open(os.path.join(folder, "mail.txt"), "w", encoding="utf-8") as f:
                        f.write("\n".join(output_lines))
                    with open(os.path.join(folder, "mail.ok"), "w") as f:
                        pass

        except Exception as e:
            print(f"Erreur lors du traitement du mail : {e}")
    elif type_co == "MICROSOFT_EXCHANGE_OAUTH2":
        try:
            client_id, client_secret, tenant_id, user_email= keys_manager.lire_config_oauth2(
                offusc_conf_agent)
            authority = f"https://login.microsoftonline.com/{tenant_id}"

            app = ConfidentialClientApplication(
                client_id=client_id,
                client_credential=client_secret,
                authority=authority
            )

            token_result = app.acquire_token_for_client(scopes=["https://outlook.office365.com/.default"])
            if "access_token" not in token_result:
                raise Exception("Impossible d'obtenir un token : ", token_result.get("error_description"))

            token_for_exchangelib = OAuth2Token({
                'access_token': token_result['access_token'],
                'expires_in': token_result.get('expires_in', 3600),
                'token_type': token_result.get('token_type', 'Bearer'),
                'scope': 'https://outlook.office365.com/.default'
            })

            credentials = OAuth2Credentials(
                client_id=client_id,
                client_secret=client_secret,
                tenant_id=tenant_id,
                identity=Identity(primary_smtp_address=user_email),
                access_token=token_for_exchangelib
            )

            config = Configuration(
                credentials=credentials,
                auth_type='OAuth 2.0',
                service_endpoint='https://outlook.office365.com/EWS/Exchange.asmx'
            )

            account = Account(
                primary_smtp_address=user_email,
                config=config,
                autodiscover=True,
                access_type=DELEGATE
            )

            inbox = account.inbox.filter(is_read=False)

            if not inbox:
                print("Aucun nouveau mail.")
            else:
                for item in inbox.order_by('datetime_received'):
                    if list_agent_email:
                        white_list, black_list = keys_manager.lire_list_email(list_agent_email)
                    else:
                        white_list, black_list = [], []

                    if not isinstance(item, Message):
                        print('mail non standard (reunion etc...), ignore')
                        continue

                    from_ = item.sender.email_address
                    subject = item.subject or "(Sans sujet)"
                    to_emails = [rec.email_address for rec in item.to_recipients or []]
                    cc_emails = [rec.email_address for rec in item.cc_recipients or []]

                    # Marquer comme lu
                    item.is_read = True
                    item.save()

                    if item.body.body_type == "HTML":
                        soup = BeautifulSoup(item.body, "html.parser")
                        for block in soup.find_all(["footer", "style", "script"]):
                            block.decompose()
                        body = soup.get_text(separator="\n", strip=True)
                    else:
                        body = item.body.strip()

                    folder = mail_in_folder(user_email, "in")
                    if folder is None:
                        print("Erreur dans le folder de mail")
                        continue

                    ignored_pj = ""
                    for attachment in item.attachments:
                        if not hasattr(attachment, 'name') or len(attachment.name) < 5:
                            continue
                        if not (attachment.name.endswith(".pdf") or attachment.name.endswith(".docx")):
                            ignored_pj += (";" if ignored_pj else "") + attachment.name
                            continue

                        folder_pj = os.path.join(folder, "pj")
                        os.makedirs(folder_pj, exist_ok=True)
                        filepath = os.path.join(folder_pj, attachment.name)
                        with open(filepath, "wb") as f:
                            f.write(attachment.content)

                    output_lines = [
                        f"#$who : {user_email}",
                        f"#$eme : {from_}",
                        f"#$des : {', '.join(to_emails)}",
                        f"#$cop : {', '.join(cc_emails)}",
                        "#$pri : Normale",
                        f"#$tit : {subject}",
                        f"#$ipj : {ignored_pj}",
                        f"#$txt : {body.strip()}",
                        ""
                    ]

                    print("----------------------------------------")
                    print(f"Mail reçu de {from_}")
                    print("----------------------------------------")

                    if white_list and from_ not in white_list:
                        print("Cette adresse n'est pas dans la white list")
                        continue
                    if black_list and from_ in black_list:
                        print("Cette adresse est dans la black list")
                        continue

                    with open(os.path.join(folder, "mail.txt"), "w", encoding="utf-8") as f:
                        f.write("\n".join(output_lines))
                    with open(os.path.join(folder, "mail.ok"), "w") as f:
                        pass
        except Exception as e:
            print(f"Erreur OAuth2 lors du traitement du mail : {e}")

    elif type_co == "MICROSOFT_EXCHANGE_OAUTH2_MICROSOFT_GRAPH":
        try:
            client_id, client_secret, tenant_id, user_email = keys_manager.lire_config_oauth2(
                offusc_conf_agent, type=type_co)

            authority = f"https://login.microsoftonline.com/{tenant_id}"

            app = ConfidentialClientApplication(
                client_id=client_id,
                client_credential=client_secret,
                authority=authority
            )

            # Essayer d'abord avec les permissions d'application (Client Credentials)
            token_result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
            if "access_token" not in token_result:
                raise Exception("Impossible d'obtenir un token : ", token_result.get("error_description"))

            access_token = token_result['access_token']
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            # Récupérer les emails non lus
            graph_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages"
            params = {
                '$filter': 'isRead eq false',
                '$orderby': 'receivedDateTime asc',
                '$select': 'id,subject,sender,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments'
            }


            try:
                response = requests.get(graph_url, headers=headers, params=params)
                response.raise_for_status()
                emails_data = response.json()
            except requests.exceptions.HTTPError as e:
                if response.status_code == 403:
                    raise Exception(
                        "❌ Permissions insuffisantes. Contactez votre IT Admin pour ajouter Mail.Read et Mail.Send permissions à l'application IA-ODATAMINING.")
                else:
                    raise e
            if not emails_data.get('value'):
                print("Aucun nouveau mail.")
            else:
                for i, email_item in enumerate(emails_data['value']):
                    if list_agent_email:
                        white_list, black_list = keys_manager.lire_list_email(list_agent_email)
                        print(f"🔍 [DEBUG] Listes chargées - White: {len(white_list)}, Black: {len(black_list)}")
                    else:
                        white_list, black_list = [], []

                    time.sleep(1.5)
                    output_lines = []

                    email_id = email_item["id"]

                    from_ = (email_item.get("from") or {}).get("emailAddress", {}).get("address")
                    if not from_:
                        from_ = (email_item.get("sender") or {}).get("emailAddress", {}).get("address")

                    subject = email_item.get("subject", "(Sans sujet)")
                    to_emails = [rec["emailAddress"]["address"] for rec in email_item.get("toRecipients", [])]
                    cc_emails = [rec["emailAddress"]["address"] for rec in email_item.get("ccRecipients", [])]

                    mark_read_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages/{email_id}"
                    requests.patch(mark_read_url, headers=headers, json={"isRead": True})
                    # Récupérer le corps du message
                    body = ""
                    if email_item.get('body'):
                        body_content = email_item['body'].get('content', '')
                        if email_item['body'].get('contentType') == 'html':
                            soup = BeautifulSoup(body_content, "html.parser")
                            for block in soup.find_all(["footer", "style", "script"]):
                                block.decompose()
                            body = soup.get_text(separator="\n", strip=True)
                        else:
                            body = body_content.strip()

                    folder = mail_in_folder(user_email, "in")
                    if folder is None:
                        print("Erreur dans le folder de mail")
                        continue

                    ignored_pj = ""
                    # Traiter les pièces jointes si elles existent
                    if email_item.get('hasAttachments'):
                        attachments_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages/{email_id}/attachments"
                        att_response = requests.get(attachments_url, headers=headers)
                        att_response.raise_for_status()
                        attachments_data = att_response.json()
                        for attachment in attachments_data.get('value', []):
                            attachment_name = attachment.get('name', '')
                            if len(attachment_name) < 5:
                                continue
                            if not (attachment_name.endswith(".pdf") or attachment_name.endswith(".docx")):
                                ignored_pj += (";" if ignored_pj else "") + attachment_name
                                continue

                            folder_pj = os.path.join(folder, "pj")
                            os.makedirs(folder_pj, exist_ok=True)
                            filepath = os.path.join(folder_pj, attachment_name)

                            # Décoder le contenu base64
                            content_bytes = base64.b64decode(attachment.get('contentBytes', ''))
                            with open(filepath, "wb") as f:
                                f.write(content_bytes)

                    # Format sortie
                    output_lines = [
                        f"#$who : {user_email}",
                        f"#$eme : {from_}",
                        f"#$des : {', '.join(to_emails)}",
                        f"#$cop : {', '.join(cc_emails)}",
                        "#$pri : Normale",
                        f"#$tit : {subject}",
                        f"#$ipj : {ignored_pj}",
                        f"#$txt : {body.strip()}",
                        ""
                    ]

                    print("----------------------------------------")
                    print(f"Mail reçu de {from_}")
                    print("----------------------------------------")

                    if white_list and from_ not in white_list:
                        print("Cette adresse n'est pas dans la white list")
                        continue
                    if black_list and from_ in black_list:
                        print("Cette adresse est dans la black list")
                        continue

                    mail_txt_path = os.path.join(folder, "mail.txt")
                    mail_ok_path = os.path.join(folder, "mail.ok")
                    with open(mail_txt_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(output_lines))
                    with open(mail_ok_path, "w") as f:
                        pass

        except Exception as e:
            print(f"Erreur Graph API lors du traitement du mail : {e}")
            print(f"🔍 [DEBUG] Erreur détaillée: {type(e).__name__}: {str(e)}")


    else:
        print("type de co non géré : attendu IMAP4_SSL, MICROSOFT_EXCHANGE_OWA ou MICROSOFT_EXCHANGE_OAUTH2")
        return


def lire_message(chemin_fichier):
    donnees = {}
    cle_courante = None
    texte_multi_ligne = []

    with open(chemin_fichier, 'r', encoding='utf-8') as fichier:
        for ligne in fichier:
            if ligne.startswith('#$'):
                if cle_courante == 'txt' and texte_multi_ligne:
                    donnees['txt'] = '\n'.join(texte_multi_ligne).strip()
                    texte_multi_ligne = []

                cle_val = ligne[2:].split(':', 1)
                cle_courante = cle_val[0].strip()

                if cle_courante == 'txt':
                    texte_multi_ligne.append(cle_val[1].strip())
                else:
                    donnees[cle_courante] = cle_val[1].strip()
            else:
                if cle_courante == 'txt':
                    texte_multi_ligne.append(ligne.rstrip())

    # En fin de fichier, enregistrer le texte si encore en cours
    if cle_courante == 'txt' and texte_multi_ligne:
        donnees['txt'] = '\n'.join(texte_multi_ligne).strip()

    return donnees




def send_mail(expediteur, offusc_conf_agent, destinataire, sujet, contenu_html, piece_jointe_paths=None, serveur="smtp.gmail.com", port=587):
    msg = EmailMessage()
    msg['From'] = expediteur
    msg['To'] = destinataire
    msg['Subject'] = sujet

    # ✅ Définir le contenu HTML comme contenu alternatif
    msg.set_content("Votre client mail ne supporte pas le HTML.")  # fallback texte brut
    msg.add_alternative(contenu_html, subtype='html')

    # ✅ Ajout d'une ou plusieurs pièces jointes si fournie
    if piece_jointe_paths:
        piece_paths = [f for f in os.listdir(piece_jointe_paths) if os.path.isfile(os.path.join(piece_jointe_paths, f))]
        for piece_path in piece_paths:
            try:
                with open(piece_jointe_paths + "/" + piece_path, 'rb') as f:
                    data = f.read()
                    nom_fichier = os.path.basename(piece_jointe_paths + "/" +piece_path)
                    type_mime, _ = mimetypes.guess_type(nom_fichier)
                    maintype, subtype = type_mime.split('/') if type_mime else ('application', 'octet-stream')
                    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=nom_fichier)
            except Exception as e:
                print(f"Erreur lors de l'ajout de la pièce jointe '{piece_path}': {e}")
    try:
        _, _, mot_de_passe, _, _ = keys_manager.lire_config_imap4_ssl(offusc_conf_agent)
        with smtplib.SMTP(serveur, port) as smtp:
            smtp.starttls()
            smtp.login(expediteur, mot_de_passe)
            smtp.send_message(msg)
        return 0
    except Exception as e:
        print("❌ Une erreur s'est produite :", e)

def extraire_emails(champ):
    """
    Transforme une chaîne du type :
    'a@test.com;b@test.com' ou 'a@test.com, b@test.com'
    en liste Python propre.
    """
    if not champ:
        return []

    emails = champ.replace(";", ",").split(",")
    return [email.strip() for email in emails if email.strip()]

def to_graph_recipients(champ):
    """
    Convertit une chaîne d'emails en format attendu par Microsoft Graph.
    """
    return [
        {
            "emailAddress": {
                "address": email
            }
        }
        for email in extraire_emails(champ)
    ]

def check_send_new_emails(offusc_conf_agent, type_co):
    if type_co == "IMAP4_SSL":
        agent, domain, _, _, alias = keys_manager.lire_config_imap4_ssl(offusc_conf_agent)
        mail = agent + domain
        if alias != "":
            agent = alias
        chemin_dossier_in, chemin_dossier_out = mail_in_folder(agent, "out")
        if os.path.exists(chemin_dossier_out) and os.path.isdir(chemin_dossier_out):
            contenus = os.listdir(chemin_dossier_out)
            if contenus:
                for contenu in contenus:
                    if os.path.exists(chemin_dossier_out + "/" + contenu + "/mail.ok"):
                        chemin = chemin_dossier_out + "/" + contenu + "/mail.txt"
                        infos = lire_message(chemin)
                        cles_requises = ["eme", "des", "cop", "pri", "tit", "txt"]
                        if all(cle in infos for cle in cles_requises):
                            destinataires = extraire_emails(infos["eme"])
                            copies = extraire_emails(infos.get("cop", ""))
                            if not destinataires:
                                print("Aucun destinataire trouvé dans 'eme'")
                                continue

                            send_mail(
                                mail,
                                offusc_conf_agent,
                                destinataires,
                                infos["tit"],
                                infos["txt"],
                                cc=copies,
                                piece_jointe_paths=chemin_dossier_out + "/" + contenu + "/pj"
                            )
                            MetManagement.reset_folder(chemin_dossier_in + contenu, recreate=False)
                            MetManagement.reset_folder(chemin_dossier_out + contenu, recreate=False)
                        else:
                            print("il manque des clefs dans le contenu du mail")
            else:
                print("Le dossier est vide.")
        else:
            print("Le dossier n'existe pas ou le chemin n'est pas un dossier.")
    elif type_co == "MICROSOFT_EXCHANGE_OWA":
        try:
            mail, alias, server, username, password, interval_second = keys_manager.lire_config_owa(
                offusc_conf_agent
            )
            credentials = Credentials(username=username, password=password)
            config = Configuration(server=server, credentials=credentials)
            account = Account(
                primary_smtp_address=alias,
                credentials=credentials,
                config=config,
                autodiscover=False,
                access_type=DELEGATE
            )

            chemin_dossier_in, chemin_dossier_out = mail_in_folder(alias, "out")
            if os.path.exists(chemin_dossier_out) and os.path.isdir(chemin_dossier_out):
                contenus = os.listdir(chemin_dossier_out)
                if contenus:
                    for contenu in contenus:
                        if os.path.exists(chemin_dossier_out + "/" + contenu + "/mail.ok"):
                            chemin = chemin_dossier_out + "/" + contenu + "/mail.txt"
                            infos = lire_message(chemin)
                            cles_requises = ["eme", "des", "cop", "pri", "tit", "txt"]
                            if all(cle in infos for cle in cles_requises):
                                to_recipients = [
                                    Mailbox(email_address=email)
                                    for email in extraire_emails(infos["eme"])
                                ]
                                cc_recipients = [
                                    Mailbox(email_address=email)
                                    for email in extraire_emails(infos.get("cop", ""))
                                ]

                                if not to_recipients:
                                    print("Aucun destinataire trouvé dans 'eme'")
                                    continue

                                m = Message(
                                    account=account,
                                    folder=account.sent,
                                    subject=infos["tit"],
                                    body=HTMLBody(infos["txt"]),
                                    to_recipients=to_recipients,
                                    cc_recipients=cc_recipients,
                                    sender=Mailbox(email_address=alias),
                                )
                                m.send_and_save()
                                time.sleep(1)
                                MetManagement.reset_folder(chemin_dossier_in + contenu, recreate=False)
                                MetManagement.reset_folder(chemin_dossier_out + contenu, recreate=False)
                            else:
                                print("il manque des clefs dans le contenu du mail")
                else:
                    print("Le dossier est vide.")

        except Exception as e:
            print(f"Erreur lors du traitement du mail : {e}")
    elif type_co == "MICROSOFT_EXCHANGE_OAUTH2":
        try:
            client_id, client_secret, tenant_id, user_email = keys_manager.lire_config_oauth2(
                offusc_conf_agent
            )
            agent = user_email
            alias = user_email

            chemin_dossier_in, chemin_dossier_out = mail_in_folder(agent, "out")
            authority = f"https://login.microsoftonline.com/{tenant_id}"

            app = ConfidentialClientApplication(
                client_id=client_id,
                client_credential=client_secret,
                authority=authority
            )
            print("app", app)
            token_result = app.acquire_token_for_client(
                scopes=["https://outlook.office365.com/.default"]
            )

            if "access_token" not in token_result:
                raise Exception(
                    f"Impossible d'obtenir un token : {token_result.get('error_description')}"
                )

            token_for_exchangelib = OAuth2Token({
                "access_token": token_result["access_token"],
                "expires_in": token_result.get("expires_in", 3600),
                "token_type": token_result.get("token_type", "Bearer"),
                "scope": "https://outlook.office365.com/.default"
            })

            credentials = OAuth2Credentials(
                client_id=client_id,
                client_secret=client_secret,
                tenant_id=tenant_id,
                identity=Identity(primary_smtp_address=user_email),
                access_token=token_for_exchangelib
            )
            config = Configuration(
                credentials=credentials,
                auth_type="OAuth 2.0",
                service_endpoint="https://outlook.office365.com/EWS/Exchange.asmx"
            )

            account = Account(
                primary_smtp_address=user_email,
                config=config,
                autodiscover=False,
                access_type=DELEGATE
            )

            if os.path.exists(chemin_dossier_out) and os.path.isdir(chemin_dossier_out):
                contenus = os.listdir(chemin_dossier_out)
                if contenus:
                    for contenu in contenus:
                        if os.path.exists(chemin_dossier_out + "/" + contenu + "/mail.ok"):
                            chemin = os.path.join(chemin_dossier_out, contenu, "mail.txt")
                            infos = lire_message(chemin)
                            cles_requises = ["eme", "des", "cop", "pri", "tit", "txt"]
                            if all(cle in infos for cle in cles_requises):
                                to_recipients = [
                                    Mailbox(email_address=email)
                                    for email in extraire_emails(infos["eme"])
                                ]
                                cc_recipients = [
                                    Mailbox(email_address=email)
                                    for email in extraire_emails(infos.get("cop", ""))
                                ]

                                if not to_recipients:
                                    print("Aucun destinataire trouvé dans 'eme'")
                                    continue

                                m = Message(
                                    account=account,
                                    folder=account.sent,
                                    subject=infos["tit"],
                                    body=HTMLBody(infos["txt"]),
                                    to_recipients=to_recipients,
                                    cc_recipients=cc_recipients,
                                    sender=Mailbox(email_address=alias),
                                )
                                m.send_and_save()
                                time.sleep(1)

                                MetManagement.reset_folder(
                                    os.path.join(chemin_dossier_in, contenu),
                                    recreate=False
                                )
                                MetManagement.reset_folder(
                                    os.path.join(chemin_dossier_out, contenu),
                                    recreate=False
                                )
                            else:
                                print("\n\n Il manque des clefs dans le contenu du mail")
                        else:
                            print(
                                "\n\n KO § os.path.exists(os.path.join(chemin_dossier_out, contenu)",
                                os.path.exists(os.path.join(chemin_dossier_out, contenu, "mail.ok"))
                            )
                else:
                    print("Le dossier est vide.")
            else:
                print("Le dossier n'existe pas ou le chemin n'est pas un dossier.")

        except Exception as e:
            print(f"❌ Erreur lors de l'envoi avec OAuth2 : {e}")

    elif type_co == "MICROSOFT_EXCHANGE_OAUTH2_MICROSOFT_GRAPH":
        try:
            client_id, client_secret, tenant_id, user_email = keys_manager.lire_config_oauth2(
                offusc_conf_agent, type_co
            )

            agent = user_email
            chemin_dossier_in, chemin_dossier_out = mail_in_folder(agent, "out")
            authority = f"https://login.microsoftonline.com/{tenant_id}"

            app = ConfidentialClientApplication(
                client_id=client_id,
                client_credential=client_secret,
                authority=authority
            )

            token_result = app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )

            if "access_token" not in token_result:
                raise Exception(
                    f"Impossible d'obtenir un token : {token_result.get('error_description')}"
                )

            access_token = token_result["access_token"]
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            if os.path.exists(chemin_dossier_out) and os.path.isdir(chemin_dossier_out):
                contenus = os.listdir(chemin_dossier_out)
                if contenus:
                    for contenu in contenus:
                        dossier_actuel = os.path.join(chemin_dossier_out, contenu)
                        mail_ok_path = os.path.join(dossier_actuel, "mail.ok")

                        if os.path.exists(mail_ok_path):
                            chemin_txt = os.path.join(dossier_actuel, "mail.txt")
                            infos = lire_message(chemin_txt)

                            cles_requises = ["eme", "des", "cop", "pri", "tit", "txt"]
                            if all(cle in infos for cle in cles_requises):

                                to_recipients = to_graph_recipients(infos["eme"])
                                cc_recipients = to_graph_recipients(infos.get("cop", ""))

                                if not to_recipients:
                                    print("Aucun destinataire trouvé dans 'eme'")
                                    continue

                                attachments = []
                                chemin_pj = os.path.join(dossier_actuel, "pj")

                                if os.path.exists(chemin_pj) and os.path.isdir(chemin_pj):
                                    for filename in os.listdir(chemin_pj):
                                        file_path = os.path.join(chemin_pj, filename)
                                        if os.path.isfile(file_path):
                                            with open(file_path, "rb") as f:
                                                content_bytes = f.read()
                                                encoded_content = base64.b64encode(content_bytes).decode("utf-8")

                                            attachments.append({
                                                "@odata.type": "#microsoft.graph.fileAttachment",
                                                "name": filename,
                                                "contentBytes": encoded_content
                                            })

                                message = {
                                    "subject": infos["tit"],
                                    "body": {
                                        "contentType": "HTML",
                                        "content": infos["txt"]
                                    },
                                    "toRecipients": to_recipients,
                                    "attachments": attachments
                                }

                                if cc_recipients:
                                    message["ccRecipients"] = cc_recipients

                                message_data = {
                                    "message": message,
                                    "saveToSentItems": True
                                }

                                send_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/sendMail"
                                try:
                                    response = requests.post(send_url, headers=headers, json=message_data)
                                    response.raise_for_status()
                                except requests.exceptions.HTTPError as e:
                                    if response.status_code == 403:
                                        raise Exception("❌ Permission Mail.Send manquante.")
                                    else:
                                        raise e

                                time.sleep(1)
                                MetManagement.reset_folder(
                                    os.path.join(chemin_dossier_in, contenu),
                                    recreate=False
                                )
                                MetManagement.reset_folder(
                                    os.path.join(chemin_dossier_out, contenu),
                                    recreate=False
                                )

        except Exception as e:
            print(f"❌ Erreur lors de l'envoi avec Graph API : {e}")
            print(f"📤 [DEBUG] Erreur détaillée: {type(e).__name__}: {str(e)}")
    else:
        print("type de co non valide")

def list_conf_files(type_co):
    conf_files = []
    if type_co is None or type_co == "":
        return conf_files
    dossier = MetManagement.get_secret_content_dir()
    dossier = dossier + type_co
    files = os.listdir(dossier)
    for file in files:
        if file.lower().endswith(".json") or file.lower().endswith(".sec") :
            conf_files.append(file)
    return conf_files



if __name__ == "__main__":
    type_co="MICROSOFT_EXCHANGE_OAUTH2_MICROSOFT_GRAPH"
    list_agent_email = []
    offusc_conf_agents = list_conf_files(type_co)
    while True:
        for offusc_conf_agent in offusc_conf_agents:
            print("offusc conf agent : ", offusc_conf_agent)
            check_new_emails(offusc_conf_agent,type_co, list_agent_email)
            time.sleep(1)
            check_send_new_emails(offusc_conf_agent,type_co)
            time.sleep(1)
