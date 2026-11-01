import json

import streamlit as st
from openai import OpenAI
from pypdf import PdfReader
from supabase import Client, create_client


st.set_page_config(
    page_title="AI 학습 정리 노트",
    page_icon="📚",
    layout="wide",
)

st.sidebar.title("AI 학습 정리 노트")
st.sidebar.caption("PDF를 업로드해 페이지별 원문을 확인하세요.")

uploaded_file = st.sidebar.file_uploader(
    "PDF 파일 업로드",
    type=["pdf"],
    accept_multiple_files=False,
)

st.title("AI 학습 정리 노트")
st.caption("업로드한 PDF를 페이지별로 확인할 수 있는 학습 대시보드입니다.")

if "summary_result" not in st.session_state:
    st.session_state.summary_result = None
if "summary_error" not in st.session_state:
    st.session_state.summary_error = None
if "summary_document_key" not in st.session_state:
    st.session_state.summary_document_key = None
if "summary_save_message" not in st.session_state:
    st.session_state.summary_save_message = None
if "summary_record_id" not in st.session_state:
    st.session_state.summary_record_id = None
if "quiz_result" not in st.session_state:
    st.session_state.quiz_result = None
if "quiz_error" not in st.session_state:
    st.session_state.quiz_error = None
if "quiz_save_message" not in st.session_state:
    st.session_state.quiz_save_message = None


@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


def has_filename_column_mismatch(error: Exception) -> bool:
    message = str(error)
    return "filename" in message and "fliename" in message


def save_summary(filename: str, summary: dict) -> int:
    client = get_supabase_client()
    payload = {
        "filename": filename,
        "summary": summary,
        "quiz": {},
    }
    try:
        response = client.table("summaries").insert(payload).execute()
    except Exception as error:
        if not has_filename_column_mismatch(error):
            raise
        payload["fliename"] = payload.pop("filename")
        response = client.table("summaries").insert(payload).execute()
    return response.data[0]["id"]


def update_summary_quiz(summary_id: int, quiz: dict) -> None:
    get_supabase_client().table("summaries").update(
        {"quiz": quiz}
    ).eq("id", summary_id).execute()


def load_summaries() -> list[dict]:
    client = get_supabase_client()
    try:
        response = (
            client.table("summaries")
            .select("id, filename, summary, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []
    except Exception as error:
        if not has_filename_column_mismatch(error):
            raise
        response = (
            client.table("summaries")
            .select("id, fliename, summary, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        records = response.data or []
        for record in records:
            record["filename"] = record.pop("fliename", "")
        return records


def delete_summary(summary_id: int) -> None:
    get_supabase_client().table("summaries").delete().eq("id", summary_id).execute()


page_count = 0
page_texts = []
full_text = ""
document_error = None

if uploaded_file is not None:
    try:
        document_key = f"{uploaded_file.name}:{uploaded_file.size}"
        if st.session_state.summary_document_key != document_key:
            st.session_state.summary_result = None
            st.session_state.summary_error = None
            st.session_state.summary_record_id = None
            st.session_state.quiz_result = None
            st.session_state.quiz_error = None
            st.session_state.quiz_save_message = None
            st.session_state.summary_document_key = document_key

        reader = PdfReader(uploaded_file)
        page_count = len(reader.pages)
        page_texts = [
            (page.extract_text() or "").strip()
            for page in reader.pages
        ]
        full_text = "\n\n".join(
            f"[{page_number}페이지]\n{page_text}"
            for page_number, page_text in enumerate(page_texts, start=1)
            if page_text
        )

        st.sidebar.divider()
        st.sidebar.subheader("문서 정보")
        st.sidebar.write(f"**파일명**  \n{uploaded_file.name}")
        st.sidebar.metric("총 페이지 수", f"{page_count}페이지")
    except Exception as error:
        document_error = str(error)

original_tab, summary_tab, quiz_tab, history_tab = st.tabs(
    ["원문", "요약", "퀴즈", "저장 기록"]
)

with original_tab:
    if document_error:
        st.error(f"PDF를 읽는 중 오류가 발생했습니다: {document_error}")
    elif uploaded_file is None:
        st.info("왼쪽 사이드바에서 PDF 파일을 업로드하세요.")
    else:
        st.subheader("페이지별 추출 텍스트")
        for page_number, page_text in enumerate(page_texts, start=1):
            with st.expander(f"{page_number}페이지", expanded=page_number == 1):
                if page_text:
                    st.text_area(
                        f"{page_number}페이지 텍스트",
                        value=page_text,
                        height=260,
                        label_visibility="collapsed",
                    )
                else:
                    st.info("이 페이지에서는 추출할 수 있는 텍스트가 없습니다.")

with summary_tab:
    st.subheader("AI 요약")
    st.write("PDF의 핵심 내용을 세 가지 항목으로 정리합니다.")

    if document_error:
        st.error(f"PDF를 읽는 중 오류가 발생했습니다: {document_error}")
    elif uploaded_file is None:
        st.info("요약하려면 먼저 PDF 파일을 업로드하세요.")
    elif not full_text:
        st.info("요약할 수 있는 텍스트가 PDF에 없습니다.")
    else:
        if st.button("요약하기", type="primary"):
            try:
                client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                system_prompt = (
                    "다음 문서를 분석하고 반드시 JSON 객체 하나만 반환하세요. "
                    "JSON에는 '핵심 요약', '주요 키워드', '난이도' 세 개의 키만 포함해야 합니다. "
                    "'핵심 요약'은 정확히 3문장으로 작성하고, "
                    "'주요 키워드'는 정확히 5개의 문자열 배열로 작성하며, "
                    "'난이도'는 '상', '중', '하' 중 하나로 작성하세요."
                )
                with st.spinner("PDF 내용을 요약하고 있습니다..."):
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": full_text},
                        ],
                        response_format={"type": "json_object"},
                    )

                response_content = response.choices[0].message.content or "{}"
                st.session_state.summary_result = json.loads(response_content)
                st.session_state.summary_error = None
                st.session_state.summary_save_message = None
            except Exception as error:
                st.session_state.summary_result = None
                st.session_state.summary_error = str(error)

        if st.session_state.summary_error:
            st.error(f"요약 중 오류가 발생했습니다: {st.session_state.summary_error}")

        summary_result = st.session_state.summary_result
        if summary_result:
            st.markdown("#### 핵심 요약")
            st.write(summary_result.get("핵심 요약", "요약 내용이 없습니다."))

            st.markdown("#### 주요 키워드")
            keywords = summary_result.get("주요 키워드", [])
            st.write(" · ".join(keywords))

            st.markdown("#### 난이도")
            st.metric("난이도", summary_result.get("난이도", "미정"))

            if st.session_state.summary_record_id:
                st.info("이 요약은 이미 저장되어 있습니다.")
            elif st.button("저장", key="save_summary_button"):
                try:
                    st.session_state.summary_record_id = save_summary(
                        uploaded_file.name,
                        summary_result,
                    )
                    st.session_state.summary_save_message = "요약을 저장했습니다."
                except Exception as error:
                    st.session_state.summary_save_message = f"저장 중 오류가 발생했습니다: {error}"

            if st.session_state.summary_save_message:
                if st.session_state.summary_save_message.startswith("저장 중 오류"):
                    st.error(st.session_state.summary_save_message)
                else:
                    st.success(st.session_state.summary_save_message)

with quiz_tab:
    st.subheader("학습 퀴즈")
    st.write("저장된 요약을 바탕으로 4지선다 퀴즈 3문항을 만듭니다.")

    if not st.session_state.summary_result:
        st.info("먼저 요약 탭에서 요약을 만들어주세요.")
    elif not st.session_state.summary_record_id:
        st.warning("퀴즈를 만들기 전에 요약 탭에서 먼저 저장해주세요.")
    else:
        if st.button("퀴즈 만들기", type="primary"):
            try:
                client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                quiz_system_prompt = """당신은 학습 퀴즈를 만드는 도우미입니다.
주어진 요약을 바탕으로 4지선다 퀴즈 3문항을 만드세요.
각 문항은 question, options(4개), answer(정답 인덱스, 0부터 시작), explanation을 포함해야 합니다.
결과는 {"questions": [...]} 형태의 JSON으로 반환하세요."""
                summary_input = json.dumps(
                    st.session_state.summary_result,
                    ensure_ascii=False,
                )
                with st.spinner("요약을 바탕으로 퀴즈를 만들고 있습니다..."):
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": quiz_system_prompt},
                            {"role": "user", "content": summary_input},
                        ],
                        response_format={"type": "json_object"},
                    )

                response_content = response.choices[0].message.content or "{}"
                quiz_result = json.loads(response_content)
                update_summary_quiz(
                    st.session_state.summary_record_id,
                    quiz_result,
                )
                st.session_state.quiz_result = quiz_result
                st.session_state.quiz_error = None
                st.session_state.quiz_save_message = "퀴즈를 저장했습니다."
            except Exception as error:
                st.session_state.quiz_error = str(error)
                st.session_state.quiz_save_message = None

        if st.session_state.quiz_error:
            st.error(f"퀴즈 생성 또는 저장 중 오류가 발생했습니다: {st.session_state.quiz_error}")
        elif st.session_state.quiz_save_message:
            st.success(st.session_state.quiz_save_message)

        quiz_result = st.session_state.quiz_result
        if quiz_result:
            for question_number, question in enumerate(
                quiz_result.get("questions", []),
                start=1,
            ):
                st.markdown(f"#### {question_number}번. {question.get('question', '')}")
                options = question.get("options", [])
                selected_option = st.radio(
                    "보기",
                    options,
                    index=None,
                    key=f"quiz_option_{st.session_state.summary_document_key}_{question_number}",
                )
                if selected_option is not None:
                    selected_index = options.index(selected_option)
                    answer_index = question.get("answer")
                    if selected_index == answer_index:
                        st.success("정답입니다!")
                    else:
                        st.error(f"오답입니다. 정답은 {answer_index + 1}번입니다.")
                    st.info(f"해설: {question.get('explanation', '해설이 없습니다.')}")

with history_tab:
    st.subheader("저장 기록")
    try:
        saved_summaries = load_summaries()
        if not saved_summaries:
            st.info("저장된 요약이 없습니다.")
        for saved_summary in saved_summaries:
            summary_data = saved_summary.get("summary") or {}
            summary_text = str(summary_data.get("핵심 요약", "요약 내용이 없습니다."))
            preview = summary_text[:120]
            if len(summary_text) > 120:
                preview += "..."

            record_columns = st.columns([2, 2, 5, 1])
            record_columns[0].write(saved_summary.get("filename", "이름 없음"))
            record_columns[1].write(
                str(saved_summary.get("created_at", "")).replace("T", " ")
            )
            record_columns[2].write(preview)
            if record_columns[3].button(
                "삭제",
                key=f"delete_summary_{saved_summary['id']}",
            ):
                try:
                    delete_summary(saved_summary["id"])
                    st.rerun()
                except Exception as error:
                    st.error(f"삭제 중 오류가 발생했습니다: {error}")
    except Exception as error:
        st.error(f"저장 기록을 불러오는 중 오류가 발생했습니다: {error}")
