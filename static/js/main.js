// static/js/main.js
document.addEventListener('DOMContentLoaded', function() {
    // Dark Mode Toggle
    const toggle = document.getElementById('darkModeToggle');
    if (toggle) {
        toggle.addEventListener('click', () => {
            document.body.classList.toggle('dark-mode');
            localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
        });
        if (localStorage.getItem('darkMode') === 'true') {
            document.body.classList.add('dark-mode');
        }
    }

    // ضبط حجم الصور المرفوعة في الدردشة عند تحميلها
    function resizeChatImages() {
        document.querySelectorAll('.message-bubble img').forEach(img => {
            img.style.maxWidth = '200px';
            img.style.maxHeight = '200px';
            img.style.objectFit = 'cover';
            img.style.borderRadius = '10px';
            img.style.cursor = 'pointer';
            img.addEventListener('click', function() {
                window.open(this.src, '_blank');
            });
        });
    }

    // مراقبة تغييرات الدردشة لضبط الصور الجديدة
    const chatBox = document.getElementById('chat-box');
    if (chatBox) {
        const observer = new MutationObserver(resizeChatImages);
        observer.observe(chatBox, { childList: true, subtree: true });
        resizeChatImages(); // للصور الموجودة مسبقًا
    }
});