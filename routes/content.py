import json

CONTENT_DB = {
    "faq": [
        {
            "question": "How do BullLogic predictions work?",
            "answer": "We train machine learning models (Linear Regression, Random Forest, and XGBoost ensembles) on years of historical price data and technical indicators for each supported asset. When you request a prediction, the models analyze the latest market data and output a predicted price, a direction (bullish or bearish), and a confidence score. Timeframes range from 1 minute to 1 day."
        },
        {
            "question": "How accurate are the predictions?",
            "answer": "It varies by asset and timeframe, and we publish it all. Every prediction on the platform is automatically graded against what the market actually did once its time horizon passes. See the live numbers on our Track Record page. Models with too few graded calls honestly show \"insufficient data\". No market prediction is ever guaranteed. Expect wrong calls regularly, even from a good model."
        },
        {
            "question": "Is this financial advice?",
            "answer": "No. BullLogic is an information and analytics tool. Nothing on the platform is a recommendation to buy or sell any asset. You are solely responsible for your trading decisions and any gains or losses. If you need personal financial advice, talk to a licensed advisor. Never trade money you cannot afford to lose."
        }
    ],
    "terms": {
        "title": "Terms of Service",
        "content": "Welcome to BullLogic. By using our service, you agree to our terms..."
    },
    "privacy": {
        "title": "Privacy Policy",
        "content": "We store your account details, prediction history, and payment records to run the service. We do not sell your personal data."
    },
    "disclosures": {
        "title": "Financial Disclosures",
        "content": "Trading involves significant risk. Our AI models do not guarantee profits."
    }
}

def register_content_routes(app):
    @app.route("/api/content/<page_id>")
    def get_content(page_id):
        from flask import jsonify
        if page_id in CONTENT_DB:
            return jsonify({"ok": True, "data": CONTENT_DB[page_id]})
        return jsonify({"ok": False, "error": "Content not found"}), 404
