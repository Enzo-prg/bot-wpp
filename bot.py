import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify
from flask_socketio import SocketIO
from pymongo import MongoClient
import requests
import os
from dotenv import load_dotenv
from openai import OpenAI
from flask_cors import CORS

# 🔹 Carregar variáveis de ambiente
load_dotenv()

# 🔹 Configuração do Flask e SocketIO para atualização em tempo real
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# 🔹 Configuração do Banco de Dados (MongoDB)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["chatbot"]
conversations = db["conversations"]
settings = db["settings"]

# 🔹 Configuração do OpenAI (ChatGPT)
openai_api_key = "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"
if not openai_api_key:
    raise ValueError("❌ OPENAI_API_KEY não foi configurada corretamente!")

openai_client = OpenAI(api_key=openai_api_key)

# 🔹 Configuração do WhatsApp API
ACCESS_TOKEN = "EAAOPTZBTiXGcBOyJn6LWnLDUIiFRq9OMDAVwthvs6PyG0xA3TdY0wZA37riLD8yvOw4cicvhhb3SzXTWDBed1GdAPTAdPQ9rubsCZCaJmGMZBZAy9TEuS9ZC6eBZAANz3TZAbvqMOFPDVfClW0lCTv9n2VIpoP9k1ZANamwytMNMrALIDcG50BhIRABI3V47OwgaZBOwZDZD"
PHONE_NUMBER_ID = "526229427249979"
VERIFY_TOKEN = "meu_token_seguro_1235"

# 🔹 Configuração do OpenAI (ChatGPT)
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("❌ OPENAI_API_KEY não foi configurada corretamente!")

# openai_client = OpenAI(api_key=openai_api_key)

# # 🔹 Configuração do WhatsApp API
# ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
# PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
# VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

if not ACCESS_TOKEN or not PHONE_NUMBER_ID or not VERIFY_TOKEN:
    raise ValueError("❌ Configuração da API WhatsApp está incompleta!")

# ✅ Função para enviar mensagens pelo WhatsApp API
def send_whatsapp_message(to, text):
    """ Envia uma mensagem via WhatsApp API """
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": text}
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=5)
        print(f"📤 [SEND] Enviando mensagem para {to}: {text}")
        print(f"📩 [WHATSAPP RESPONSE] Status: {response.status_code}, Resposta: {response.text}")

        if response.status_code != 200:
            print(f"❌ Erro ao enviar mensagem para {to}: {response.text}")

        return response.json()
    except requests.RequestException as e:
        print(f"⚠️ Erro de conexão ao enviar mensagem para {to}: {str(e)}")
        return None

# ✅ Função para obter resposta do ChatGPT
def get_chatgpt_response(user_message):
    """ Usa o ChatGPT para gerar uma resposta para o usuário """
    try:
        print(f"🤖 [CHATGPT] Pergunta: {user_message}")

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Você é um assistente virtual especializado em atendimento ao cliente."},
                {"role": "user", "content": user_message}
            ]
        )

        bot_response = response.choices[0].message.content.strip()
        print(f"✅ [CHATGPT] Resposta: {bot_response}")
        return bot_response
    except Exception as e:
        print(f"❌ [CHATGPT] Erro ao obter resposta: {str(e)}")
        return "Desculpe, estou com dificuldades para responder no momento."

# ✅ Webhook para WhatsApp
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        verify_token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if verify_token == VERIFY_TOKEN:
            print("✅ Webhook validado com sucesso!")
            return challenge, 200
        else:
            print("❌ Token de verificação inválido!")
            return "Token inválido", 403

    elif request.method == "POST":
        data = request.get_json()
        print(f"📩 [WEBHOOK] Payload recebido: {data}")

        if not data:
            return jsonify({"status": "error", "message": "Nenhum dado recebido"}), 400

        # ✅ Responde imediatamente para evitar timeout e processa depois
        eventlet.spawn_n(process_whatsapp_message, data)
        return jsonify({"status": "received"}), 200

def process_whatsapp_message(data):
    """Processa a mensagem do WhatsApp em segundo plano."""
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                if "messages" in value:
                    for msg in value["messages"]:
                        sender_id = msg.get("from", "")
                        text = msg.get("text", {}).get("body", "")

                        if not sender_id or not text:
                            print("⚠️ Mensagem recebida está vazia ou inválida.")
                            continue

                        print(f"📥 [NOVA MENSAGEM] De {sender_id}: {text}")

                        # ✅ Salva no banco de dados
                        conversations.insert_one({
                            "phone": sender_id,
                            "message": text,
                            "from_user": True
                        })

                        socketio.emit("new_message", {"phone": sender_id, "message": text, "from_user": True})

                        # ✅ Gera resposta do ChatGPT e envia para o usuário
                        response_text = get_chatgpt_response(text)
                        if not response_text:
                            print("⚠️ Resposta do ChatGPT vazia, não será enviada.")
                            continue

                        send_whatsapp_message(sender_id, response_text)

                        conversations.insert_one({
                            "phone": sender_id,
                            "message": response_text,
                            "from_user": False
                        })

                        socketio.emit("new_message", {"phone": sender_id, "message": response_text, "from_user": False})

    except Exception as e:
        print(f"❌ [PROCESS MESSAGE] Erro ao processar mensagem: {str(e)}")

# ✅ Rota principal para testar o servidor
@app.route("/")
def home():
    return jsonify({"status": "Servidor rodando no Render! 🚀"}), 200

# ✅ Inicializa o servidor no Render
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=True)
