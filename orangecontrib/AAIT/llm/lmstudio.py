import requests
import json

def get_model_lmstudio():
    # Configuration des options de la requête
    url = "http://127.0.0.1:1234/v1/models"
    headers = {
        "Content-Type": "application/json"
    }

    try:
        # Envoi de la requête POST
        response = requests.get(url, headers=headers)

        # Vérification de la réponse
        if response.status_code != 200:
            raise Exception("Erreur dans la requête")

        # Analyse du JSON de la réponse
        return response.json()

    except Exception as e:
        print(f"Erreur : {e}")
        return "Error"


def appel_lmstudio(prompt, model, stream=False, temperature=0.7, max_tokens=4096):
    # Configuration des options de la requête
    url = "http://127.0.0.1:1234/v1/chat/completions"
    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": [
            {"role": "user",
             "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream
    }

    try:
        # Envoi de la requête POST
        response = requests.post(url, headers=headers, data=json.dumps(data), stream=True)

        # Vérification de la réponse
        if response.status_code != 200:
            raise Exception("Error in the request")

        # Initialisation de la variable de contenu
        content = ""
        if stream == True:
            # Lecture et traitement du streaming
            for chunk in response.iter_lines(decode_unicode=True):
                if chunk:
                    line = chunk.strip()
                    print(line)
                    if line == "data: [DONE]":
                        break

                    if line.startswith("data: "):
                        json_data = json.loads(line[6:])
                        text = json_data.get("choices", [{}])[0].get("delta", {}).get("content", "")

                        if text:
                            content += text

        if stream == False:
            # Analyse du JSON de la réponse
            response_data = response.json()
            # Extraction du contenu du message
            content = response_data.get("choices", [{}])[0].get("message", {}).get("content", None)
        return content

    except Exception as e:
        print(f"Error : {e}")
        return None

