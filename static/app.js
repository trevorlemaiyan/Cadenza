document.addEventListener('DOMContentLoaded', () => {
    // Only run chat logic if we're on the chat page
    if (typeof ROOM_ID === 'undefined') return;

    const socket = io();
    const chatDiv = document.getElementById('chat');
    const form = document.getElementById('chat-form');
    const input = document.getElementById('message');

    // Join the private room for this match pair
    socket.emit('join', { room: ROOM_ID });

    socket.on('message', (data) => {
        appendMessage(data.sender, data.msg, false);
    });

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        const msg = input.value.trim();
        if (!msg) return;

        // Show own message immediately
        appendMessage('You', msg, true);

        socket.emit('message', { room: ROOM_ID, msg: msg, sender: MY_NAME });
        input.value = '';
    });

    function appendMessage(sender, text, isSelf) {
        const wrapper = document.createElement('div');
        wrapper.classList.add('message', isSelf ? 'message-self' : 'message-other');

        const label = document.createElement('span');
        label.classList.add('message-sender');
        label.textContent = sender;

        const bubble = document.createElement('div');
        bubble.classList.add('bubble');
        bubble.textContent = text;

        wrapper.appendChild(label);
        wrapper.appendChild(bubble);
        chatDiv.appendChild(wrapper);
        chatDiv.scrollTop = chatDiv.scrollHeight;
    }
});
