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

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

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

# Global MCP client instance
mcp_client = None

@app.route('/')
def index():
    return render_template('chat.html')

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
    global mcp_client
    
    if not mcp_client:
        return jsonify({
            'status': 'error',
            'message': 'MCP server not started'
        })
    
    user_message = request.json.get('message', '')
    
    # Simple command parsing
    if user_message.startswith('/list'):
        # List directory command
        parts = user_message.split(' ', 1)
        if len(parts) > 1:
            directory_path = parts[1]
        else:
            directory_path = "C:/Users/hclraik/Downloads"
        
        response = mcp_client.call_tool("list_directory", {"path": directory_path})
        
        if 'result' in response:
            content = response['result']['content']
            if content and len(content) > 0:
                return jsonify({
                    'status': 'success',
                    'message': f"Directory listing for {directory_path}:",
                    'content': content[0]['text']
                })
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'No content returned'
                })
        else:
            return jsonify({
                'status': 'error',
                'message': response.get('error', 'Unknown error')
            })
    
    elif user_message.startswith('/tools'):
        # List available tools
        tools_response = mcp_client.list_tools()
        if 'result' in tools_response:
            tools = tools_response['result'].get('tools', [])
            tools_text = "\n".join([f"- {tool['name']}: {tool['description']}" for tool in tools])
            return jsonify({
                'status': 'success',
                'message': 'Available tools:',
                'content': tools_text
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to get tools list'
            })
    
    else:
        return jsonify({
            'status': 'info',
            'message': 'Available commands:',
            'content': '/list [path] - List directory contents\n/tools - Show available tools'
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