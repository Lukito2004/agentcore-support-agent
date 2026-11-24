"""Customer chat app: sign in with Cognito and talk to the support agent on AgentCore Runtime.

Run from ui/: uv run streamlit run chat_app.py
"""

import streamlit as st

from auth import AuthError, CognitoAuth, Tokens, token_claims
from config import load_config
from runtime_client import AgentError, RuntimeClient, new_session_id

# Same limit the agent enforces, so the user hears about it before sending.
MAX_PROMPT_CHARS = 4000
ERROR_MESSAGES = {
    "UNAUTHENTICATED": "Your sign-in has expired. Please sign in again.",
    "SESSION_FORBIDDEN": "This conversation cannot be continued. Please start a new one.",
    "INVALID_REQUEST": "That message could not be sent. Please shorten or rephrase it.",
    "TOOLS_UNAVAILABLE": "Order tools are unavailable right now. Please try again in a minute.",
    "THROTTLED": "The assistant is busy right now. Please try again in a minute.",
}
DEFAULT_ERROR = "The assistant could not answer. Please try again."

st.set_page_config(page_title="AnyCompany Support", page_icon=":material/support_agent:")


@st.cache_resource
def services() -> tuple[CognitoAuth, RuntimeClient]:
    config = load_config()
    return (
        CognitoAuth(config.chat_client_id, config.region),
        RuntimeClient(config.region, config.runtime_arn),
    )


def start_conversation() -> None:
    st.session_state.session_id = new_session_id()
    st.session_state.messages = []


def end_session(auth: CognitoAuth, notice: str | None = None) -> None:
    tokens: Tokens | None = st.session_state.get("tokens")
    if tokens:
        auth.sign_out(tokens)
    st.session_state.clear()
    if notice:
        st.session_state.notice = notice
    st.rerun()


def sign_in_page(auth: CognitoAuth) -> None:
    st.title("AnyCompany support")
    if notice := st.session_state.pop("notice", None):
        st.info(notice)
    with st.form("sign_in"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if not submitted:
        return
    try:
        st.session_state.tokens = auth.sign_in(email.strip(), password)
    except AuthError as exc:
        st.error(str(exc))
        return
    start_conversation()
    st.rerun()


def reply(auth: CognitoAuth, runtime: RuntimeClient, prompt: str) -> str:
    try:
        tokens = auth.fresh(st.session_state.tokens)
    except AuthError as exc:
        end_session(auth, str(exc))
    st.session_state.tokens = tokens
    try:
        text = st.write_stream(
            runtime.stream_reply(tokens.access_token, st.session_state.session_id, prompt)
        )
    except AgentError as exc:
        if exc.code == "UNAUTHENTICATED":
            end_session(auth, ERROR_MESSAGES[exc.code])
        text = ERROR_MESSAGES.get(exc.code, DEFAULT_ERROR)
        st.warning(text)
    return text if isinstance(text, str) else "".join(map(str, text))


def chat_page(auth: CognitoAuth, runtime: RuntimeClient) -> None:
    customer_id = token_claims(st.session_state.tokens.access_token).get("customer_id", "")
    with st.sidebar:
        st.caption(f"Signed in as customer {customer_id}")
        if st.button("New conversation", icon=":material/add_comment:"):
            start_conversation()
            st.rerun()
        if st.button("Sign out", icon=":material/logout:"):
            end_session(auth)

    st.title("AnyCompany support")
    st.caption("Ask about your orders, your account or a refund.")
    # Markdown only; Streamlit does not render HTML from model output.
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Type your message", max_chars=MAX_PROMPT_CHARS)
    if not prompt:
        return
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        answer = reply(auth, runtime, prompt)
    st.session_state.messages.append({"role": "assistant", "content": answer})


auth, runtime = services()
if "tokens" in st.session_state:
    chat_page(auth, runtime)
else:
    sign_in_page(auth)
