from flask import Flask, jsonify

def create_app():
   app = Flask(__name__)
   
   @app.get("/api/health")
   def health_check():
        return jsonify({"status": "ok", "application": "NyumbaFlow API"})
    
   return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)