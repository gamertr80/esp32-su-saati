import os
from flask import Flask, request, jsonify, send_file
import google.generativeai as genai
from PIL import Image
import io

app = Flask(__name__)

# API Anahtarını Render Ortam Değişkenlerinden Alır
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

LAST_IMAGE_PATH = "latest_meter.jpg"

@app.route('/')
def home():
    return "ESP32-CAM AI Su Saati Sunucusu Bulutta Çalışıyor!"

@app.route('/upload-meter', methods=['POST'])
def upload_meter():
    try:
        image_bytes = request.data
        if not image_bytes:
            return jsonify({"error": "Resim verisi alınamadı"}), 400

        # 1. Çekilen son resmi dosyaya kaydet
        with open(LAST_IMAGE_PATH, "wb") as f:
            f.write(image_bytes)

        # 2. Gemini AI ile Görüntüyü İşle
        image = Image.open(io.BytesIO(image_bytes))
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = "Bu bir su sayacı görüntüsüdür. Lütfen sadece siyah ve kırmızı çarklardaki okunan sayısal indeksi yaz. Ekstra hiçbir açıklama yapma, sadece sayıları dön."
        response = model.generate_content([prompt, image])
        meter_reading = response.text.strip()

        print(f"Okunan Sayaç Değeri: {meter_reading}")

        return jsonify({
            "status": "success",
            "reading": meter_reading
        }), 200

    except Exception as e:
        print(f"Hata oluştu: {str(e)}")
        return jsonify({"error": str(e)}), 500

# CANLI GÖRÜNTÜLEME ADRESİ
@app.route('/latest-image', methods=['GET'])
def get_latest_image():
    if os.path.exists(LAST_IMAGE_PATH):
        return send_file(LAST_IMAGE_PATH, mimetype='image/jpeg')
    else:
        return jsonify({"message": "Henüz yüklenmiş bir fotoğraf yok."}), 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
