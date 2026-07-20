import os
import json
import subprocess
import sys
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication

class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return  # Override to bypass CSRF cookies validation check

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "pipeline_config.json")
CLI_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "framework_cli.py")
PYTHON_EXE = sys.executable

@method_decorator(csrf_exempt, name='dispatch')
class PipelineConfigView(APIView):
    """API endpoint to retrieve and modify pipeline_config.json configurations."""
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            if not os.path.exists(CONFIG_PATH):
                return Response({"ok": False, "error": "Configuration file not found"}, status=404)
            with open(CONFIG_PATH, "r") as f:
                config_data = json.load(f)
            return Response({"ok": True, "config": config_data})
        except Exception as e:
            return Response({"ok": False, "error": str(e)}, status=500)
            
    def post(self, request):
        try:
            config_data = request.data.get("config")
            if not config_data:
                return Response({"ok": False, "error": "Missing config body"}, status=400)
            with open(CONFIG_PATH, "w") as f:
                json.dump(config_data, f, indent=2)
            return Response({"ok": True, "message": "Configuration saved successfully"})
        except Exception as e:
            return Response({"ok": False, "error": str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class PipelineRunView(APIView):
    """API endpoint to execute pipeline steps via framework subprocesses."""
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        mode = request.data.get("mode") # "ingest", "train", "predict"
        symbol = request.data.get("symbol", "SPY")
        interval = request.data.get("interval", "1d")
        
        if mode not in ["ingest", "train", "predict"]:
            return Response({"ok": False, "error": f"Invalid mode: {mode}"}, status=400)
            
        try:
            cmd = [PYTHON_EXE, CLI_PATH, "--mode", mode, "--symbol", symbol, "--interval", interval]
            # Run command synchronously with a 15-second timeout and capture logs
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                cwd=os.path.dirname(CLI_PATH)
            )
            
            logs = result.stdout + "\n" + result.stderr
            ok = (result.returncode == 0)
            
            # Simple parser to fetch prediction output parameters if in predict mode
            prediction_data = None
            if mode == "predict" and ok:
                try:
                    prediction_data = {}
                    lines = result.stdout.split("\n")
                    for line in lines:
                        if "Direction:" in line:
                            prediction_data["direction"] = line.split("Direction:")[1].strip()
                        elif "Entry Price:" in line:
                            prediction_data["entry_price"] = line.split("Entry Price:")[1].strip().replace("$", "")
                        elif "Stop Loss:" in line:
                            prediction_data["stop_price"] = line.split("Stop Loss:")[1].strip().replace("$", "")
                        elif "Take Profit:" in line:
                            prediction_data["target_price"] = line.split("Take Profit:")[1].strip().replace("$", "")
                        elif "Confidence:" in line:
                            prediction_data["confidence"] = line.split("Confidence:")[1].strip()
                except Exception:
                    prediction_data = None

            return Response({
                "ok": ok,
                "logs": logs,
                "prediction": prediction_data
            })
        except subprocess.TimeoutExpired:
            return Response({"ok": False, "error": "Execution timeout expired (15s limit)", "logs": "Timeout expired while executing subprocess pipeline."})
        except Exception as e:
            return Response({"ok": False, "error": str(e)}, status=500)
