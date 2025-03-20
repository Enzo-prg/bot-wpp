from flask import Flask, request, jsonify
from flask_socketio import SocketIO
from pymongo import MongoClient
import requests
import os
from dotenv import load_dotenv
from openai import OpenAI
from flask_cors import CORS

# Carregar variáveis do ambiente (se estiver usando .env)
load_dotenv()

# Configuração do Flask e SocketIO para atualização em tempo real
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Conexão com MongoDB para armazenar mensagens
client = MongoClient("mongodb://localhost:27017/")
db = client["chatbot"]
conversations = db["conversations"]
settings = db["settings"]

# Configuração do OpenAI (ChatGPT)
openai_api_key = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=openai_api_key)

# Configuração do WhatsApp API
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

# Verificação das credenciais
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

    print(f"📤 Enviando mensagem para {to}: {text}")
    
    response = requests.post(url, headers=headers, json=data)
    print(f"📩 Resposta da API WhatsApp: {response.status_code}, {response.text}")

    if response.status_code != 200:
        print(f"❌ Erro ao enviar mensagem para {to}: {response.text}")

    return response.json()


# ✅ Função para obter resposta do ChatGPT
def get_chatgpt_response(user_message):
    """ Usa o ChatGPT para gerar uma resposta para o usuário """
    try:
        print(f"🤖 [OpenAI] Chamando OpenAI para mensagem: {user_message}")
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Você é um assistente virtual especializado em atendimento ao cliente."},
                {"role": "user", "content": user_message}
            ]
        )
        bot_response = response.choices[0].message.content.strip()
        print(f"✅ [OpenAI] Resposta gerada: {bot_response}")
        return bot_response
    except Exception as e:
        print(f"❌ [OpenAI] Erro ao obter resposta do ChatGPT: {str(e)}")
        return "Desculpe, estou com dificuldades para responder no momento."


# ✅ Webhook para validação e processamento de mensagens recebidas
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        # Validação do webhook na Meta
        verify_token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        print(f"🔍 Recebido GET para validação do webhook - Token recebido: {verify_token}")

        if verify_token == VERIFY_TOKEN:
            print("✅ Webhook validado com sucesso!")
            return challenge, 200
        else:
            print("❌ Token de verificação inválido!")
            return "Token inválido", 403

    elif request.method == "POST":
        # Processa mensagens recebidas do WhatsApp
        data = request.get_json()
        print(f"📩 Webhook recebeu payload: {data}")

        if not data:
            print("❌ Erro: Nenhum dado recebido no webhook!")
            return jsonify({"status": "error", "message": "Nenhum dado recebido"}), 400

        if "entry" in data:
            for entry in data["entry"]:
                for change in entry["changes"]:
                    value = change.get("value", {})

                    if "messages" in value:
                        for msg in value["messages"]:
                            sender_id = msg.get("from", "")
                            text = msg.get("text", {}).get("body", "")

                            if not sender_id or not text:
                                print(f"⚠️ Mensagem inválida recebida: {msg}")
                                continue  # Ignora mensagens sem conteúdo válido

                            print(f"📥 Nova mensagem recebida de {sender_id}: {text}")

                            # ✅ Salva mensagem recebida no MongoDB
                            conversations.insert_one({
                                "phone": sender_id,
                                "message": text,
                                "from_user": True
                            })

                            # ✅ Atualiza painel em tempo real no frontend
                            socketio.emit("new_message", {"phone": sender_id, "message": text, "from_user": True})

                            # ✅ Gera resposta do ChatGPT e envia para o usuário
                            response_text = get_chatgpt_response(text)
                            send_whatsapp_message(sender_id, response_text)

                            # ✅ Salva resposta do bot no MongoDB
                            conversations.insert_one({
                                "phone": sender_id,
                                "message": response_text,
                                "from_user": False
                            })

                            # ✅ Atualiza painel no frontend
                            socketio.emit("new_message", {"phone": sender_id, "message": response_text, "from_user": False})

        return jsonify({"status": "success"}), 200


# ✅ Enviar mensagens manualmente pelo painel
@app.route("/send-message", methods=["POST"])
def send_message():
    data = request.get_json()
    phone = data.get("phone")
    message = data.get("message")

    if not phone or not message:
        return jsonify({"status": "error", "message": "Número e mensagem são obrigatórios!"}), 400

    send_whatsapp_message(phone, message)

    # ✅ Salvar no banco de dados
    conversations.insert_one({"phone": phone, "message": message, "from_user": False})

    # ✅ Atualizar painel
    socketio.emit("new_message", {"phone": phone, "message": message, "from_user": False})

    return jsonify({"status": "success"}), 200


# ✅ Retornar todas as conversas registradas
@app.route("/conversations", methods=["GET"])
def get_conversations():
    messages = list(conversations.find({}, {"_id": 0}))
    return jsonify(messages)


# ✅ Ativar ou desativar o bot para um número específico
@app.route("/toggle-bot/<phone>", methods=["POST"])
def toggle_bot(phone):
    """Ativa ou desativa o bot para um número específico"""
    
    user_setting = settings.find_one({"phone": phone})
    
    if user_setting:
        new_status = not user_setting["bot_enabled"]
        settings.update_one({"phone": phone}, {"$set": {"bot_enabled": new_status}})
    else:
        new_status = True  # Se não existir, ativa o bot por padrão
        settings.insert_one({"phone": phone, "bot_enabled": new_status})

    print(f"🔄 Bot para {phone} atualizado para: {new_status}")  # LOG

    return jsonify({"phone": phone, "bot_enabled": new_status})


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8000, debug=True)
