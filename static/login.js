const loginForm = document.querySelector("#loginForm");
const loginButton = document.querySelector("#loginButton");
const loginMessage = document.querySelector("#loginMessage");

function showMessage(message, tone = "error") {
  loginMessage.textContent = message;
  loginMessage.classList.remove("hidden", "success", "error");
  loginMessage.classList.add(tone);
}

async function login(event) {
  event.preventDefault();

  const username = document.querySelector("#username").value.trim();
  const password = document.querySelector("#password").value;

  loginButton.disabled = true;
  loginButton.textContent = "登录中...";
  loginMessage.classList.add("hidden");

  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "登录失败，请稍后重试。");
    }

    showMessage(payload.message || "登录成功，正在跳转...", "success");
    window.setTimeout(() => {
      window.location.href = "/";
    }, 250);
  } catch (error) {
    showMessage(error.message || "登录失败，请稍后重试。", "error");
  } finally {
    loginButton.disabled = false;
    loginButton.textContent = "进入系统";
  }
}

if (loginForm) {
  loginForm.addEventListener("submit", login);
}
