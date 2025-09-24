function redirectToLogin() {
    window.location.href = LOGOUT_URLS.login;
}
document.addEventListener('keydown', redirectToLogin, { once: true });
document.addEventListener('mousedown', redirectToLogin, { once: true });