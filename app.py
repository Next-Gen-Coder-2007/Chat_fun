from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*")
chat_rooms = {}
room_members = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_room', methods=['POST'])
def create_room():
    room_name = request.form.get('room_name', 'Unnamed Room')
    room_id = str(uuid.uuid4())[:8]
    
    chat_rooms[room_id] = {
        'name': room_name,
        'messages': []
    }
    room_members[room_id] = []
    
    return redirect(url_for('chat_room', room_id=room_id))

@app.route('/join/<room_id>')
def join_room_page(room_id):
    if room_id not in chat_rooms:
        return "Room not found!", 404
    return render_template('join.html', room_id=room_id, room_name=chat_rooms[room_id]['name'])

@app.route('/chat/<room_id>')
def chat_room(room_id):
    if room_id not in chat_rooms:
        return "Room not found!", 404
    
    username = request.args.get('username', 'Anonymous')
    session['username'] = username
    session['room_id'] = room_id
    
    return render_template('chat.html', 
                         room_id=room_id, 
                         room_name=chat_rooms[room_id]['name'],
                         username=username,
                         messages=chat_rooms[room_id]['messages'])

@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    
    join_room(room)
    
    if username not in room_members.get(room, []):
        room_members[room].append(username)
    
    emit('status', {
        'msg': f'{username} has joined the room.',
        'username': username
    }, room=room)

@socketio.on('leave')
def on_leave(data):
    username = data['username']
    room = data['room']
    
    leave_room(room)
    
    if username in room_members.get(room, []):
        room_members[room].remove(username)
    
    emit('status', {
        'msg': f'{username} has left the room.',
        'username': username
    }, room=room)

@socketio.on('message')
def handle_message(data):
    room = data['room']
    username = data['username']
    message = data['message']
    
    msg_data = {
        'username': username,
        'message': message
    }
    
    chat_rooms[room]['messages'].append(msg_data)
    
    emit('message', msg_data, room=room)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
