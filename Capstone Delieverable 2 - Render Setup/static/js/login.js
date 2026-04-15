const registerBtn = document.getElementById('Register');
const container = document.getElementById('container_login');
const loginBtn = document.getElementById('Login')

registerBtn.addEventListener('click', () =>{
    container.classList.add("active");
});

loginBtn.addEventListener('click', () =>{
    container.classList.remove("active");
});