from pymongo import MongoClient
from threading import Thread
import os
import shutil
import subprocess
from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit
from flask_bcrypt import Bcrypt

app = Flask(__name__)

app.jinja_env.variable_start_string = '[['
app.jinja_env.variable_end_string = ']]'

app.config['SECRET_KEY'] = 'your_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")
bcrypt = Bcrypt(app)

client = MongoClient('localhost', 27017)
db = client['live_code_share']

#users -> user_name, user_password
#rooms -> room_name, room_password, Admin, [users], directory
#user_rooms -> user_name, [rooms]

#active_users -> user_name, room_name, client_id, file_open
#active_rooms -> room_name, active_users -> user_name, client_id
active_users = []
active_rooms = []
clients = {}

@app.route('/')
def login_signup():
    return render_template('login_signup.html')

@socketio.on('connect')
def handle_connect():
    print('client connected')
    global clients
    client_id = request.sid
    print('client id when connected:', client_id)
    emit('receive_client_id', {'client_id': client_id})
    print('emitted client id:', client_id)

@app.route('/signup', methods = ['POST'])
def signup():
    global clients
    user_name = request.form['user_name']
    user_password = request.form['user_password']
    hashed_user_password = bcrypt.generate_password_hash(user_password).decode('utf-8')
    users = db['users']
    user = users.find_one({'user_name': user_name})
    if user is None:
        users.insert_one({'user_name': user_name, 'user_password': hashed_user_password})
        global active_users
        active_users.append({'user_name': user_name, 'room_name': '', 'client_id': '', 'file_open': ''})
        user_rooms = db['user_rooms']
        user_rooms.insert_one({'user_name': user_name, 'rooms': []})
        return redirect(url_for('create_join'))
    else:
        return render_template('login_signup.html')

@app.route('/login', methods = ['POST'])    
def login():
    global clients
    user_name = request.form['user_name']
    user_password = request.form['user_password']
    users = db['users']
    user = users.find_one({'user_name': user_name})
    if user is not None and bcrypt.check_password_hash(user['user_password'], user_password):
        global active_users
        active_users.append({'user_name': user_name, 'room_name': '', 'client_id': '', 'file_open': ''})
        return redirect(url_for('create_join'))
    else:
        return render_template('login_signup.html')
    
@app.route('/create_join')
def create_join():
    return render_template('create_join.html')  

@socketio.on('create_join_room')
def create_join_room(user_name):
    user_rooms = db['user_rooms']
    user_room = user_rooms.find_one({'user_name': user_name})
    print('emitted user: ',user_name,' all rooms:', user_room['rooms'])
    emit('receive_join_room', {'user_all_rooms': user_room['rooms']})
    #user_all_rooms is a list containing all rooms the user has joined to display in create join page

def update_active_users_list(active_users_list_of_dictionary, client_id):
    print('inside update active users list', active_users_list_of_dictionary)
    active_users_list = []
    for active_user in active_users_list_of_dictionary:
        active_users_list.append(active_user['user_name'])
    for active_user in active_users_list_of_dictionary:
        client_id = active_user['client_id']
        socketio.emit('active_users_list', {'active_users_list': active_users_list}, room = client_id)

def update_room_directory(room_directory_dict, active_users_dict, client_id):
    print('inside update room directory', room_directory_dict, active_users_dict)
    for active_user in active_users_dict:
        client_id = active_user['client_id']
        socketio.emit('room_directory', {'room_directory': room_directory_dict}, room = client_id)


@app.route('/create', methods = ['POST'])
def create():
    room_name = request.form['room_name']
    room_password = request.form['room_password']
    user_name = request.form['user_name']
    hashed_room_password = bcrypt.generate_password_hash(room_password).decode('utf-8')
    rooms = db['rooms']
    room = rooms.find_one({'room_name': room_name})
    if room is None:
        rooms.insert_one({'room_name': room_name, 'room_password': hashed_room_password, 'Admin': user_name, 'users': [user_name], 'directory': {}})
        global active_users
        for user in active_users:
            if user.get('user_name') == user_name:
                user['room_name'] = room_name
                break
        global active_rooms
        active_rooms.append({'room_name': room_name, 'active_users': [{'user_name': user_name, 'client_id': ''}]})
        user_rooms = db['user_rooms']
        user_rooms.update_one({'user_name': user_name}, {'$push': {'rooms': room_name}})
        os.makedirs(os.path.join('rooms',room_name))
        return redirect(url_for('main'))
    else:
        return redirect(url_for('create_join'))
    

def join_room(user_name, room_name, room):
    rooms = db['rooms']
    global active_users
    for user in active_users:
        if user.get('user_name') == user_name:
            user['room_name'] = room_name
            break
    global active_rooms
    active_room = next((room for room in active_rooms if room.get('room_name') == room_name), None)
    if active_room is not None:
        for room in active_rooms:
            if room.get('room_name') == room_name:
                if 'active_users' not in room:
                    room['active_users'] = []
                room['active_users'].append({
                    'user_name': user_name,
                    'client_id': ''
                })
                break
    else:
        active_rooms.append({'room_name': room_name, 'active_users': [{'user_name': user_name, 'client_id':''}]})
    user_rooms = db['user_rooms']
    user_room = user_rooms.find_one({'user_name': user_name})
    if room_name not in user_room['rooms']:
        user_rooms.update_one({'user_name': user_name}, {'$push': {'rooms': room_name}})
    room_user = rooms.find_one({'room_name': room_name})
    if user_name not in room_user['users']:
        rooms.update_one({'room_name': room_name}, {'$push': {'users': user_name}})


@socketio.on('direct_join')
def direct_join(user_name, room_name):
    print('inside direct join', user_name, room_name)
    rooms = db['rooms']
    print(1)
    room = rooms.find_one({'room_name': room_name})
    print(2)
    join_room(user_name, room_name, room)
    print(3)
    emit('redirect', {'url': '/main'})

@app.route('/join', methods = ['POST'])
def join():
    room_name = request.form['room_name']
    room_password = request.form['room_password']
    user_name = request.form['user_name']
    rooms = db['rooms']
    room = rooms.find_one({'room_name': room_name})
    print(room)
    if room is not None and bcrypt.check_password_hash(room['room_password'], room_password):
        join_room(user_name, room_name, room)
        return redirect(url_for('main'))
    else:
        return redirect(url_for('create_join'))
    

@app.route('/main')
def main():
    return render_template('main.html')     
    
#this is the format of the room directory
#{'abc': {'abc/ab.txt': 'file'}, 'def': {'def/gh.txt': 'file', 'def/ij.py': 'file'}}}
@socketio.on('main_page')
def main_page(user_name, room_name):
    global clients
    client_id = request.sid
    clients[client_id] = {'user_name': user_name, 'room_name': room_name}
    global active_users
    for user in active_users:
        if user.get('user_name') == user_name:
            user['client_id'] = client_id
            break
    global active_rooms
    for room in active_rooms:
        if room['room_name'] == room_name:
            for user in room['active_users']:
                if user['user_name'] == user_name:
                    user['client_id'] = client_id
                    break
            break
    rooms = db['rooms']
    room = rooms.find_one({'room_name': room_name})
    room_users = room['users']
    print('got room users', room_users)
    active_room = next((room for room in active_rooms if room.get('room_name') == room_name), None)
    active_users_dict = active_room['active_users']
    active_users_list = []
    for active_user in active_users_dict:
        active_users_list.append(active_user['user_name'])
    print('got active users list', active_users_list)
    #Thread(target = update_active_users_list, args = (active_room['active_users'], client_id)).start()
    rooms = db['rooms']
    room = rooms.find_one({'room_name': room_name})
    room_directory = room['directory']
    print('got room directory', room_directory)
    emit('receive_main_page', {'room_name': room_name, 'user_name': user_name, 'room_users': room_users, 'active_users_list': active_users_list, 'room_directory': room_directory}, room = client_id)
#room_users is a list containing all users joined the room (not only active), also includes the initial active user list and room directory to be displayed


@app.route('/back')
def back():
    global clients
    client_id = request.args.get('client_id')
    user_name = clients[client_id]['user_name']
    room_name = clients[client_id]['room_name']
    global active_users
    for user in active_users:
        if user.get('user_name') == user_name:
            user.update({'room_name': '', 'file_open': ''})
            break
    global active_rooms
    for room in active_rooms:
        if room.get('room_name') == room_name and 'active_users' in room:
            room['active_users'] = [user for user in room['active_users'] if user.get('user_name') != user_name 
                                    or user.get('client_id') != client_id]
            break
    active_room = next((room for room in active_rooms if room.get('room_name') == room_name), None)
    Thread(target = update_active_users_list, args = (active_room['active_users'], client_id)).start()
    if active_room['active_users'] == []:
        active_rooms = [room for room in active_rooms if room.get('room_name') != room_name]
    clients[client_id]['room_name'] = ''
    return redirect(url_for('create_join'))

@app.route('/logout')
def logout():
    user_name = request.args.get('user_name')
    global active_users
    active_users = [user for user in active_users if user.get('user_name') != user_name]
    return render_template('login_signup.html')


@socketio.on('create_folder')
def create_folder(folder_path, folder_name):
    global clients
    client_id = request.sid
    folder_path = os.path.join(folder_path, folder_name)
    print(folder_path)
    room_name = clients[client_id]['room_name']
    print('sending create folder')
    try:
        os.makedirs(os.path.join('rooms', room_name, folder_path))
        rooms = db['rooms']
        room = rooms.find_one({'room_name': room_name})
        room_directory = room['directory']
        room_directory_copy = room_directory
        folders = folder_path.lstrip('/').split('/')
        print(folders)
        for folder in folders[:-1]:
            if folder != '':
                room_directory_copy = room_directory_copy[folder]
        room_directory_copy[folder_path] = {}
        rooms.update_one({'room_name': room_name}, {'$set': {'directory': room_directory}})
        global active_rooms
        active_room = next((room for room in active_rooms if room.get('room_name') == room_name), None)
        Thread(target = update_room_directory, args = (room['directory'], active_room['active_users'], client_id)).start()
        status = 'success'
    except OSError:
        status = 'failure'
    return emit('create_folder_status', {'status': status}, room = client_id) #status for create folder (success or failure)

@socketio.on('create_file')
def create_file(file_path, file_name):
    global clients
    client_id = request.sid
    file_path = os.path.join(file_path, file_name)
    room_name = clients[client_id]['room_name']
    try:
        with open(os.path.join('rooms', room_name, file_path), 'w') as file:
            pass
        rooms = db['rooms']
        room = rooms.find_one({'room_name': room_name})
        room_directory = room['directory']
        room_directory_copy = room_directory
        folders = file_path.lstrip('/').split('/')
        for folder in folders[:-1]:
            if folder != '':
                room_directory_copy = room_directory_copy[folder]
        room_directory_copy[file_path] = 'file'
        rooms.update_one({'room_name': room_name}, {'$set': {'directory': room_directory}})
        global active_rooms
        active_room = next((room for room in active_rooms if room.get('room_name') == room_name), None)
        Thread(target = update_room_directory, args = (room['directory'], active_room['active_users'], client_id)).start()
        status = 'success'
    except:
        status = 'failure'
    return emit('create_file_status', {'status': status}, room = client_id) #status for create file (success or failure)

@socketio.on('delete_folder')
def delete_folder(folder_path, folder_name):
    global clients
    client_id = request.sid
    folder_path = os.path.join(folder_path, folder_name)
    room_name = clients[client_id]['room_name']
    try:
        os.rmdir(os.path.join('rooms', room_name, folder_path))
        rooms = db['rooms']
        room = rooms.find_one({'room_name': room_name})
        room_directory = room['directory']
        room_directory_copy = room_directory
        folders = folder_path.lstrip('/').split('/')
        for folder in folders[:-1]:
            if folder != '':
                room_directory_copy = room_directory_copy[folder]
        del room_directory_copy[folder_path]
        rooms.update_one({'room_name': room_name}, {'$set': {'directory': room_directory}})
        global active_rooms
        active_room = next((room for room in active_rooms if room.get('room_name') == room_name), None)
        Thread(target = update_room_directory, args = (room['directory'], active_room['active_users'], client_id)).start()
        status = 'success'
    except:
        status = 'failure'
    return emit('delete_folder_status', {'status': status}, room = client_id) #status for delete folder (success or failure)

@socketio.on('delete_file')
def delete_file(file_path, file_name):
    global clients
    client_id = request.sid
    file_path = os.path.join(file_path, file_name)
    room_name = clients[client_id]['room_name']
    try:
        os.remove(os.path.join('rooms', room_name, file_path))
        rooms = db['rooms']
        room = rooms.find_one({'room_name': room_name})
        room_directory = room['directory']
        room_directory_copy = room_directory
        folders = file_path.lstrip('/').split('/')
        for folder in folders[:-1]:
            if folder != '':
                room_directory_copy = room_directory_copy[folder]
        del room_directory_copy[file_path]
        rooms.update_one({'room_name': room_name}, {'$set': {'directory': room_directory}})
        global active_rooms
        active_room = next((room for room in active_rooms if room.get('room_name') == room_name), None)
        Thread(target = update_room_directory, args = (room['directory'], active_room['active_users'],client_id)).start()
        status = 'success'
    except:
        status = 'failure'
    return emit('delete_file_status', {'status': status}, room = client_id) #status for delete file (success or failure)

@socketio.on('rename_folder')
def rename_folder(old_folder_path, new_folder_name):
    global clients
    client_id = request.sid
    folder_path = os.path.dirname(old_folder_path)
    new_folder_path = os.path.join(folder_path, new_folder_name)
    room_name = clients[client_id]['room_name']
    try:
        os.rename(os.path.join('rooms', room_name, old_folder_path), os.path.join('rooms', room_name, new_folder_path))
        rooms = db['rooms']
        room = rooms.find_one({'room_name': room_name})
        room_directory = room['directory']
        room_directory_copy = room_directory
        folders = old_folder_path.lstrip('/').split('/')
        for folder in folders[:-1]:
            if folder != '':
                room_directory_copy = room_directory_copy[folder]
        room_directory_copy[new_folder_path] = room_directory_copy[old_folder_path]
        del room_directory_copy[old_folder_path]
        rooms.update_one({'room_name': room_name}, {'$set': {'directory': room_directory}})
        global active_rooms
        active_room = next((room for room in active_rooms if room.get('room_name') == room_name), None)
        Thread(target = update_room_directory, args = (room['directory'], active_room['active_users'], client_id)).start()
        status = 'success'
    except:
        status = 'failure'
    return emit('rename_folder_status', {'status': status}, room = client_id) #status for rename folder (success or failure)

@socketio.on('rename_file')
def rename_file(old_file_path, new_file_name):
    global clients
    client_id = request.sid
    folder_path = os.path.dirname(old_file_path)
    new_file_path = os.path.join(folder_path, new_file_name)
    room_name = clients[client_id]['room_name']
    try:
        os.rename(os.path.join('rooms', room_name, old_file_path), os.path.join('rooms', room_name, new_file_path))
        rooms = db['rooms']
        room = rooms.find_one({'room_name': room_name})
        room_directory = room['directory']
        room_directory_copy = room_directory
        folders = old_file_path.lstrip('/').split('/')
        for folder in folders[:-1]:
            if folder != '':
                room_directory_copy = room_directory_copy[folder]
        room_directory_copy[new_file_path] = room_directory_copy[old_file_path]
        del room_directory_copy[old_file_path]
        rooms.update_one({'room_name': room_name}, {'$set': {'directory': room_directory}})
        global active_rooms
        active_room = next((room for room in active_rooms if room.get('room_name') == room_name), None)
        Thread(target = update_room_directory, args = (room['directory'], active_room['active_users'], client_id)).start()
        status = 'success'
    except:
        status = 'failure'
    return emit('rename_file_status', {'status': status}, room = client_id) #status for rename file (success or failure)


@socketio.on('open_file')
def open_file(file_path):
    global clients
    client_id = request.sid
    user_name = clients[client_id]['user_name']
    room_name = clients[client_id]['room_name']
    try:
        with open(os.join.path('rooms', room_name, file_path), 'r') as file:
            content = file.read()
        global active_users
        for user in active_users:
            if user.get('user_name') == user_name and user.get('room_name') == room_name:
                user['file_open'] = file_path
                break
        return emit('open_file_content', {'status': 'success', 'content': content}, room = client_id) #status for open file (success) and content of the file
    except:
        return emit('open_file_content', {'status': 'failure'}, room = client_id) #status for open file (failure)
        
@socketio.on('execute')
def execute(command, inputs):
    global clients
    client_id = request.sid
    room_name = clients[client_id]['room_name']
    if command:
        try:
            result = None
            if inputs:
                input_data = '\n'.join(inputs)
                terminal_room_name = os.path.join('rooms', room_name)
                result = subprocess.run(command, input=input_data, text=True, shell=True, capture_output=True, cwd = terminal_room_name)
            if result and result.stdout:
                output = result.stdout.strip()
            elif result and result.stderr:
                return result.stderr.strip()
            else:
                output = ''
        except Exception as e:
            output = str(e)
    else:
        output = ''
    #print(output)
    return emit('execute_output', {'output': output}, room = client_id) #output of the command


def change_file(room_name, code, file_path):
    try:
        with open(os.path.join('rooms', room_name, file_path), 'r') as file:
            lines = file.readlines()

        start_line, start_ch = code['from']['line'], code['from']['ch']
        end_line, end_ch = code['to']['line'], code['to']['ch']
        old_text = code['removed']
        new_text = code['text']

        if start_line == end_line:
            lines[start_line] = lines[start_line][:start_ch] + lines[start_line][end_ch:]
        else:
            lines[start_line] = lines[start_line][:start_ch]
            lines[end_line] = lines[end_line][end_ch:]
            del lines[start_line + 1:end_line]

        lines[start_line] = lines[start_line] + new_text[0]
        for i in range(1, len(new_text)):
            lines.insert(start_line + i, new_text[i])

        with open(os.path.join(room_name, file_path), 'w') as file:
            file.writelines(lines)
    except:
        pass


@socketio.on('receive_changed_code')
def receive_changed_data(code):
    global clients
    client_id = request.sid
    user_name = clients[client_id]['user_name']
    room_name = clients[client_id]['room_name']
    file_path = code['file_path']
    print('code is',code, file_path)
    if file_path:
        Thread(target = change_file, args = (room_name, code, file_path)).start()
        global active_users
        file_active_users = [user for user in active_users if user.get('user_name') == user_name 
                        and user.get('room_name') == room_name 
                        and user.get('file_open') == file_path]
        for file_active_user in file_active_users:
            client_id = file_active_user['client_id']
            emit('send_changed_code', {'code': code, 'file_path': file_path}, room = client_id)

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')
    global clients
    global active_users
    client_id = request.sid
    active_user = next((user for user in active_users if user.get('client_id') == client_id), None)
    if active_user is not None:
        active_user_name = active_user['user_name']
        active_room_name = active_user['room_name']
        active_users = [user for user in active_users if user.get('client_id') != client_id]
        global active_rooms
        for room in active_rooms:
            if room.get('room_name') == active_room_name and 'active_users' in room:
                room['active_users'] = [user for user in room['active_users'] 
                                         if user.get('user_name') != active_user_name 
                                         or user.get('client_id') != client_id]
                break
        active_room = next((room for room in active_rooms if room.get('room_name') == active_room_name), None)
        if active_room is not None:
            Thread(target = update_active_users_list, args = (active_room['active_users'], client_id)).start()
            if active_room['active_users'] == []:
                active_rooms = [room for room in active_rooms if room.get('room_name') != active_room_name]
        for client in clients:
            if client == client_id:
                del clients[client]
                break


if __name__ == '__main__':
    socketio.run(app, host = '0.0.0.0', port = 1234)