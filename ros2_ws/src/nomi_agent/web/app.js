const chat = document.getElementById("chat");

const input = document.getElementById(
    "messageInput"
);

const sendButton = document.getElementById(
    "sendButton"
);

const statusText = document.getElementById(
    "status"
);


function addMessage(
    text,
    type
) {
    const div = document.createElement(
        "div"
    );

    div.className =
        `message ${type}`;

    div.textContent = text;

    chat.appendChild(div);

    chat.scrollTop =
        chat.scrollHeight;
}


async function sendMessage() {

    const text =
        input.value.trim();

    if (!text) {
        return;
    }

    addMessage(
        text,
        "user"
    );

    input.value = "";

    try {

        const response =
            await fetch(
                "/api/chat",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        message: text
                    })
                }
            );

        const data =
            await response.json();

        addMessage(
            data.message,
            "bot"
        );

    } catch (error) {

        addMessage(
            "NOMI 서버와 연결할 수 없습니다.",
            "bot"
        );

        console.error(error);
    }
}


sendButton.addEventListener(
    "click",
    sendMessage
);


input.addEventListener(
    "keydown",
    event => {

        if (event.key === "Enter") {
            sendMessage();
        }

    }
);


async function checkStatus() {

    try {

        const response =
            await fetch(
                "/api/status"
            );

        if (response.ok) {

            statusText.textContent =
                "● 연결됨";

        }

    } catch {

        statusText.textContent =
            "● 연결 안 됨";
    }
}


checkStatus();
