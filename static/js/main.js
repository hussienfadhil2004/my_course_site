document.addEventListener('DOMContentLoaded', function(){
    const toggle = document.getElementById('darkModeToggle');
    if (toggle) {
        toggle.addEventListener('click', () => {
            document.body.classList.toggle('dark-mode');
            localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
        });
        if (localStorage.getItem('darkMode') === 'true') document.body.classList.add('dark-mode');
    }
});