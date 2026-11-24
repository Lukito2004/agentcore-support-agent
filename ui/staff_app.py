"""Staff app: approve or reject refunds waiting for review. Uses your own AWS credentials.

Run from ui/: uv run streamlit run staff_app.py --server.port 8502
"""

import sys
from pathlib import Path

import streamlit as st

# Shares the review logic with scripts/approve_refund.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import refund_review  # noqa: E402

st.set_page_config(page_title="Refund approvals", page_icon=":material/fact_check:")


@st.cache_resource
def refunds_table():
    return refund_review.refunds_table()


def decide(refund_id: str, approve: bool, note: str) -> None:
    try:
        with st.spinner("Sending the decision..."):
            result = refund_review.decide(refunds_table(), refund_id, approve, note)
    except refund_review.ReviewError as exc:
        st.error(str(exc))
        return
    st.session_state.notice = f"{refund_id} is now {result['status']}."
    st.rerun()


st.title("Refunds waiting for approval")
if notice := st.session_state.pop("notice", None):
    st.success(notice)
if st.button("Refresh", icon=":material/refresh:"):
    st.rerun()

refunds = refund_review.pending_refunds(refunds_table())
if not refunds:
    st.info("No refunds are waiting for approval.")

for refund in refunds:
    refund_id = refund["refund_id"]
    with st.container(border=True):
        st.subheader(
            f"{float(refund['amount']):.2f} {refund['currency']} for order {refund['order_id']}"
        )
        # Customer text is shown as plain text, never as markdown.
        st.text(f"{refund_id}, customer {refund['customer_id']}, asked {refund['created_at']}")
        st.text(f"Reason: {refund['reason']}")
        note = st.text_input("Note (required to reject)", key=f"note-{refund_id}", max_chars=500)
        approve_col, reject_col = st.columns(2)
        if approve_col.button("Approve", key=f"approve-{refund_id}", type="primary"):
            decide(refund_id, True, note)
        if reject_col.button("Reject", key=f"reject-{refund_id}"):
            decide(refund_id, False, note)
