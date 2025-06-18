from flask import Flask, render_template, request, jsonify, session
import asyncio
import json
import subprocess
import uuid
import os
import sys
from datetime import datetime
import threading
import queue
import time
import requests
import re

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

# Groq API configuration
GROQ_API_KEY = None  # Will be set when user provides it
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

class GroqClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def chat_completion(self, messages, model="llama-3.1-70b-versatile", max_tokens=1000):
        """Send a chat completion request to Groq"""
        try:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.7
            }
            
            response = requests.post(GROQ_API_URL, headers=self.headers, json=payload)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            return {"error": str(e)}

class MCPClient:
    def __init__(self, server_command):
        self.server_command = server_command
        self.process = None
        self.request_id = 0
        
    def start_server(self):
        """Start the MCP server process"""
        try:
            # Try to determine the correct working directory
            possible_dirs = [
                "C:/Users/hclraik/Downloads/demo/servers/src/filesystem",
                "./",
                os.getcwd()
            ]
            
            server_dir = None
            for dir_path in possible_dirs:
                if os.path.exists(dir_path):
                    server_dir = dir_path
                    break
            
            print(f"Starting server in directory: {server_dir}")
            print(f"Command: {' '.join(self.server_command)}")
            
            self.process = subprocess.Popen(
                self.server_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0,
                cwd=server_dir,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            )
            
            # Give server time to start
            time.sleep(1)
            
            # Check if process is still running
            if self.process.poll() is None:
                print("Server process started successfully")
                return True
            else:
                stderr_output = self.process.stderr.read()
                stdout_output = self.process.stdout.read()
                print(f"Server failed to start.")
                print(f"Stderr: {stderr_output}")
                print(f"Stdout: {stdout_output}")
                return False
                
        except Exception as e:
            print(f"Failed to start server: {e}")
            return False
    
    def send_request(self, method, params=None):
        """Send a JSON-RPC request to the MCP server"""
        if not self.process:
            return {"error": "Server not started"}
        
        self.request_id += 1
        request_obj = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method
        }
        
        if params is not None:
            request_obj["params"] = params
        
        try:
            # Send request
            request_json = json.dumps(request_obj) + "\n"
            print(f"Sending: {request_json.strip()}")  # Debug log
            
            self.process.stdin.write(request_json)
            self.process.stdin.flush()
            
            # Read response with polling (Windows compatible)
            max_attempts = 50  # 5 seconds total
            attempt = 0
            
            while attempt < max_attempts:
                if self.process.poll() is not None:
                    return {"error": "Server process terminated"}
                
                # Try to read a line
                try:
                    # Use a short timeout approach
                    import threading
                    result = {"response": None, "error": None}
                    
                    def read_line():
                        try:
                            line = self.process.stdout.readline()
                            if line:
                                result["response"] = line.strip()
                        except Exception as e:
                            result["error"] = str(e)
                    
                    thread = threading.Thread(target=read_line)
                    thread.daemon = True
                    thread.start()
                    thread.join(timeout=0.1)  # 100ms timeout
                    
                    if result["response"]:
                        print(f"Received: {result['response']}")  # Debug log
                        return json.loads(result["response"])
                    elif result["error"]:
                        return {"error": f"Read error: {result['error']}"}
                    
                except Exception as e:
                    return {"error": f"Communication error: {str(e)}"}
                
                time.sleep(0.1)
                attempt += 1
            
            return {"error": "Server response timeout"}
                
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON response: {str(e)}"}
        except Exception as e:
            return {"error": f"Communication error: {str(e)}"}
    
    def list_tools(self):
        """List available tools"""
        return self.send_request("tools/list")
    
    def call_tool(self, tool_name, arguments):
        """Call a specific tool"""
        return self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
    
    def stop_server(self):
        """Stop the MCP server process"""
        if self.process:
            self.process.terminate()
            self.process.wait()

# Global client instances
mcp_client = None
groq_client = None

def analyze_user_intent(user_message, available_tools):
    """Use Groq to analyze user intent and determine if MCP tools should be used"""
    if not groq_client:
        return None, "Groq client not initialized"
    
    tools_description = "\n".join([f"- {tool['name']}: {tool['description']}" for tool in available_tools])
    
    system_prompt = f"""You are an intelligent assistant that helps users interact with filesystem tools. 

Available tools:
{tools_description}

Your job is to analyze the user's request and determine:
1. If they need to use any of the available tools
2. What tool to use and with what parameters
3. Provide a natural language response

If the user is asking about files, directories, or filesystem operations, you should use the appropriate tool.
If it's a general conversation, respond naturally without using tools.

Respond in JSON format:
{{
    "use_tool": true/false,
    "tool_name": "tool_name_if_needed",
    "tool_params": {{"param": "value"}},
    "response": "Your natural language response"
}}

If use_tool is true, keep the response brief and let the tool results speak for themselves.
If use_tool is false, provide a complete conversational response.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    try:
        response = groq_client.chat_completion(messages, max_tokens=500)
        
        if "error" in response:
            return None, f"Groq API error: {response['error']}"
        
        content = response['choices'][0]['message']['content']
        
        # Try to parse JSON response
        try:
            intent_data = json.loads(content)
            return intent_data, None
        except json.JSONDecodeError:
            # If JSON parsing fails, treat as general conversation
            return {
                "use_tool": False,
                "tool_name": None,
                "tool_params": None,
                "response": content
            }, None
            
    except Exception as e:
        return None, f"Error analyzing intent: {str(e)}"

def format_tool_result_with_groq(user_message, tool_result, tool_name):
    """Use Groq to format tool results in a conversational way"""
    if not groq_client:
        return str(tool_result)
    
    system_prompt = f"""You are a helpful assistant. The user asked: "{user_message}"

I used the {tool_name} tool and got this result:
{json.dumps(tool_result, indent=2)}

Please provide a natural, conversational response that summarizes the result in a user-friendly way.
If it's a directory listing, format it nicely. If it's file content, present it clearly.
Be concise but informative."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Please format this result for me."}
    ]
    
    try:
        response = groq_client.chat_completion(messages, max_tokens=800)
        
        if "error" in response:
            return f"Tool result: {tool_result}"
        
        return response['choices'][0]['message']['content']
        
    except Exception as e:
        return f"Tool result: {tool_result}"

@app.route('/')
def index():
    return render_template('chat.html')

@app.route('/set_groq_key', methods=['POST'])
def set_groq_key():
    global groq_client, GROQ_API_KEY
    
    api_key = request.json.get('api_key', '').strip()
    
    if not api_key:
        return jsonify({
            'status': 'error',
            'message': 'API key is required'
        })
    
    GROQ_API_KEY = api_key
    groq_client = GroqClient(api_key)
    
    # Test the API key
    test_response = groq_client.chat_completion([
        {"role": "user", "content": "Hello"}
    ], max_tokens=10)
    
    if "error" in test_response:
        groq_client = None
        GROQ_API_KEY = None
        return jsonify({
            'status': 'error',
            'message': f'Invalid API key: {test_response["error"]}'
        })
    
    return jsonify({
        'status': 'success',
        'message': 'Groq API key set successfully'
    })

@app.route('/start_server', methods=['POST'])
def start_server():
    global mcp_client
    
    # Path to your compiled MCP server
    server_path = request.json.get('server_path', 'node dist/index.js --stdio')
    
    mcp_client = MCPClient(server_path.split())
    
    if mcp_client.start_server():
        # Send initialize request first
        init_response = mcp_client.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {
                    "listChanged": True
                },
                "sampling": {}
            },
            "clientInfo": {
                "name": "flask-mcp-client",
                "version": "1.0.0"
            }
        })
        
        print(f"Initialize response: {init_response}")
        
        if 'result' in init_response:
            # Send initialized notification
            mcp_client.send_request("notifications/initialized")
            
            # Now get tools list
            tools_response = mcp_client.list_tools()
            print(f"Tools response: {tools_response}")
            
            tools = []
            if 'result' in tools_response:
                tools = tools_response['result'].get('tools', [])
            
            session['tools'] = tools
            
            return jsonify({
                'status': 'success',
                'message': 'MCP server started successfully',
                'tools': tools
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f'Failed to initialize MCP server: {init_response.get("error", "Unknown error")}'
            })
    else:
        return jsonify({
            'status': 'error',
            'message': 'Failed to start MCP server'
        })

@app.route('/chat', methods=['POST'])
def chat():
    global mcp_client, groq_client
    
    if not groq_client:
        return jsonify({
            'status': 'error',
            'message': 'Please set your Groq API key first'
        })
    
    if not mcp_client:
        return jsonify({
            'status': 'error',
            'message': 'MCP server not started'
        })
    
    user_message = request.json.get('message', '')
    available_tools = session.get('tools', [])
    
    # Analyze user intent with Groq
    intent_data, error = analyze_user_intent(user_message, available_tools)
    
    if error:
        return jsonify({
            'status': 'error',
            'message': error
        })
    
    if intent_data['use_tool'] and intent_data['tool_name']:
        # Execute the tool
        tool_response = mcp_client.call_tool(
            intent_data['tool_name'], 
            intent_data['tool_params'] or {}
        )
        
        if 'result' in tool_response:
            # Format the result with Groq
            formatted_response = format_tool_result_with_groq(
                user_message, 
                tool_response['result'], 
                intent_data['tool_name']
            )
            
            return jsonify({
                'status': 'success',
                'message': formatted_response,
                'tool_used': intent_data['tool_name'],
                'raw_result': tool_response['result']
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f"Tool error: {tool_response.get('error', 'Unknown error')}"
            })
    else:
        # Regular conversation response
        return jsonify({
            'status': 'success',
            'message': intent_data['response']
        })

@app.route('/stop_server', methods=['POST'])
def stop_server():
    global mcp_client
    
    if mcp_client:
        mcp_client.stop_server()
        mcp_client = None
        
    return jsonify({
        'status': 'success',
        'message': 'MCP server stopped'
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)