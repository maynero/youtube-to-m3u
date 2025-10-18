import subprocess
import json
import logging
from flask import Flask, request, Response, jsonify, url_for, redirect
from urllib.parse import unquote
import os
from threading import Lock
from datetime import datetime

# Ensure UTF-8 encoding for subprocesses
os.environ['PYTHONIOENCODING'] = 'utf-8'

app = Flask(__name__)

# Set up logging with UTF-8 encoding
logging.basicConfig(level=logging.INFO, encoding='utf-8')

# Global process manager to track running streamlink processes


class StreamProcessManager:
    def __init__(self):
        # {url: {'process': subprocess, 'quality': str, 'clients': set, 'start_time': datetime}}
        self.processes = {}
        self.lock = Lock()  # Thread safety for process management

    def get_process(self, url, quality):
        """Get an existing process or create a new one if it doesn't exist"""
        client_ip = request.remote_addr
        user_agent = request.headers.get('User-Agent', 'Unknown')
        client_info = (client_ip, user_agent)

        with self.lock:
            if url in self.processes:
                existing_process = self.processes[url]['process']

                if existing_process.poll() is not None:
                    # Process has ended, remove it and create a new one
                    logging.info(f"Stream process for {url} has ended. Restarting.")
                    del self.processes[url]
                    return self.run_streamlink(url, quality, client_info)

                self.processes[url]['clients'].add(client_info)
                return existing_process
            else:
                return self.run_streamlink(url, quality, client_info)

    def run_streamlink(self, url, quality, client_info):
        # Create new process
        command = [
            'streamlink',
            url,
            quality,
            '--hls-live-restart',
            '--stdout'
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.processes[url] = {
            'process': process,
            'quality': quality,
            'clients': {client_info},
            'start_time': datetime.now()
        }
        logging.info(f"Started new stream process for {url} with quality {quality}")
        return process

    def remove_client(self, url, client_addr, user_agent='Unknown'):
        """Remove a client from the process. If no clients left, the process continues running."""
        client_info = (client_addr, user_agent)
        with self.lock:
            if url in self.processes:
                self.processes[url]['clients'].discard(client_info)
                logging.info(
                    f"Client {client_addr} ({user_agent}) removed from stream {url}. Current clients: {len(self.processes[url]['clients'])}")

    def kill_process(self, url):
        """Kill a specific process"""
        with self.lock:
            if url in self.processes:
                process_info = self.processes[url]
                process = process_info['process']
                if process.poll() is None:  # Process is still running
                    process.terminate()
                    try:
                        process.wait(timeout=5)  # Wait for process to finish
                    except subprocess.TimeoutExpired:
                        process.kill()  # Force kill if it doesn't terminate gracefully
                    process.stdout.close()
                    process.stderr.close()
                    logging.info(f"Killed stream process for {url}")
                del self.processes[url]
                return True
            return False

    def kill_all_processes(self):
        """Kill all running processes"""
        with self.lock:
            urls_to_remove = list(self.processes.keys())
            for url in urls_to_remove:
                self.kill_process(url)

    def get_process_info(self):
        """Get information about all running processes"""
        with self.lock:
            info = []
            for url, process_info in self.processes.items():
                process = process_info['process']
                is_running = process.poll() is None
                # Format clients as list of dictionaries with IP and user agent
                formatted_clients = []
                for client_tuple in process_info['clients']:
                    if isinstance(client_tuple, tuple) and len(client_tuple) == 2:
                        client_ip, user_agent = client_tuple
                        formatted_clients.append({
                            'ip': client_ip,
                            'user_agent': user_agent
                        })
                    else:
                        # Fallback for old format (just IP)
                        formatted_clients.append({
                            'ip': client_tuple,
                            'user_agent': 'Unknown'
                        })

                info.append({
                    'url': url,
                    'quality': process_info['quality'],
                    'clients': formatted_clients,
                    'running': is_running,
                    'start_time': process_info['start_time'].isoformat()
                })
            return info


# Initialize the global process manager
stream_manager = StreamProcessManager()


@app.route('/')
def index():
    return redirect(url_for('manage_processes'))


@app.route('/stream', methods=['GET'])
def stream():
    url = unquote(request.args.get('url'))  # Decode URL-encoded characters
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400

    quality = request.args.get('quality', 'best')

    try:
        # Get stream info with more detailed output
        info_command = ['streamlink', '--json', '--loglevel', 'debug', url]
        info_process = subprocess.Popen(
            info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        info_output, info_error = info_process.communicate()

        if info_process.returncode != 0:
            error_msg = info_error.decode('utf-8', errors='replace')
            logging.error(f'Streamlink error: {error_msg}')
            return jsonify({'error': 'Failed to retrieve stream info', 'details': error_msg}), 500

        # Parse the JSON output
        stream_info = json.loads(info_output.decode('utf-8', errors='replace'))

        # Check if streams are available
        if 'streams' not in stream_info or not stream_info['streams']:
            if 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
                yt_command = ['youtube-dl', '--get-url',
                              '--youtube-skip-dash-manifest', url]
                yt_process = subprocess.Popen(
                    yt_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                yt_url, yt_error = yt_process.communicate()

                if yt_process.returncode != 0:
                    logging.error(
                        f"youtube-dl error: {yt_error.decode('utf-8', errors='replace')}")
                    return jsonify({'error': 'No valid streams found'}), 404

                url = yt_url.decode('utf-8', errors='replace').strip()
                info_command = ['streamlink', '--json', url]
                info_process = subprocess.Popen(
                    info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                info_output, info_error = info_process.communicate()
                stream_info = json.loads(
                    info_output.decode('utf-8', errors='replace'))

        best_quality = stream_info['streams'].get(quality)
        if not best_quality:
            return jsonify({'error': 'No valid streams found'}), 404

        # Get or create the process for this URL
        process = stream_manager.get_process(url, quality)
        client_ip = request.remote_addr
        user_agent = request.headers.get('User-Agent', 'Unknown')

        def generate():
            try:
                logging.info(
                    f"Client {client_ip} ({user_agent}) connected to stream {url} using quality {quality}")
                while True:
                    data = process.stdout.read(4096)
                    if not data:
                        # This could mean the stream ended
                        break
                    yield data
            except GeneratorExit:
                logging.info(
                    f"Client {client_ip} ({user_agent}) disconnected from stream {url}")
                # Don't terminate the process, just remove the client
                stream_manager.remove_client(url, client_ip, user_agent)
            except Exception as e:
                logging.error(
                    f'Error in generator for {client_ip} ({user_agent}): {str(e)}')
                # Don't terminate the process, just remove the client
                stream_manager.remove_client(url, client_ip, user_agent)

        response = Response(generate(), content_type='video/mp2t')

        @response.call_on_close
        def cleanup():
            # Don't terminate the process, just remove the client
            stream_manager.remove_client(url, client_ip, user_agent)
            logging.info(
                f"Client {client_ip} ({user_agent}) cleaned up from stream {url}")

        return response

    except Exception as e:
        logging.error(f'Error occurred: {str(e)}')
        return jsonify({'error': str(e)}), 500


@app.route('/processes', methods=['GET', 'POST'])
def manage_processes():
    """Manage running stream processes.

    GET: Show a web page with running processes and kill buttons
    POST: Kill a specific process by URL or all processes
    """
    if request.method == 'POST':
        # Handle killing process(es) from web form
        url = request.form.get('url')  # URL of the specific process to kill
        # Action: 'kill' or 'kill_all'
        action = request.form.get('action', 'kill')

        if action == 'kill_all':
            # Kill all processes
            stream_manager.kill_all_processes()
            message = 'All processes killed successfully'
        elif url:
            # Kill specific process
            success = stream_manager.kill_process(url)
            if success:
                message = f'Process for URL {url} killed successfully'
            else:
                message = f'No process found for URL {url}'
        else:
            message = 'No URL provided to kill process'

        # Return HTML page with the message and updated process list
        process_info = stream_manager.get_process_info()
        html = generate_processes_page(process_info, message)
        return html

    # GET request - show the processes page
    process_info = stream_manager.get_process_info()
    html = generate_processes_page(process_info)
    return html


def generate_processes_page(process_info, message=None):
    """Generate HTML page for process management"""
    html = '''
<!DOCTYPE html>
<html>
<head>
    <title>YouTube-to-M3U Process Manager</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        .status-running { color: green; }
        .status-stopped { color: red; }
        .kill-btn { background-color: #ff4444; color: white; border: none; padding: 5px 10px; cursor: pointer; }
        .kill-btn:hover { background-color: #cc0000; }
        .kill-all-btn { background-color: #ff0000; color: white; border: none; padding: 10px 20px; cursor: pointer; margin-top: 10px; }
        .kill-all-btn:hover { background-color: #cc0000; }
        .message { color: green; font-weight: bold; margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1>YouTube-to-M3U Process Manager</h1>
'''
    if message:
        html += f'<div class="message">{message}</div>\n'

    html += '''
    <h2>Running Processes</h2>
    <table>
        <tr>
            <th>URL</th>
            <th>Quality</th>
            <th>Clients</th>
            <th>Status</th>
            <th>Start Time</th>
            <th>Action</th>
        </tr>
'''
    for process in process_info:
        status_class = 'status-running' if process['running'] else 'status-stopped'
        status_text = 'Running' if process['running'] else 'Stopped'
        # Format clients with both IP and user agent
        clients_list = ''
        if process['clients']:
            client_items = []
            for client in process['clients']:
                if isinstance(client, dict) and 'ip' in client:
                    client_display = f"{client['ip']} ({client['user_agent']})"
                else:
                    # Fallback for simple string format
                    client_display = str(client)
                client_items.append(client_display)
            clients_list = '<br>'.join(client_items)
        else:
            clients_list = 'None'

        html += f'''
        <tr>
            <td>{process['url']}</td>
            <td>{process['quality']}</td>
            <td>{clients_list}</td>
            <td class="{status_class}">{status_text}</td>
            <td>{process['start_time']}</td>
            <td>
                <form method="post" style="display: inline;">
                    <input type="hidden" name="url" value="{process['url']}">
                    <input type="hidden" name="action" value="kill">
                    <button type="submit" class="kill-btn" onclick="return confirm('Are you sure you want to kill this process?')">Kill</button>
                </form>
            </td>
        </tr>
'''
    html += '''
    </table>
    <form method="post" style="margin-top: 20px;">
        <input type="hidden" name="action" value="kill_all">
        <button type="submit" class="kill-all-btn" onclick="return confirm('Are you sure you want to kill ALL processes?')">Kill All Processes</button>
    </form>
    <p><em>Total running processes: {}
    </em></p>
</body>
</html>
'''.format(len(process_info))
    return html


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6095)
