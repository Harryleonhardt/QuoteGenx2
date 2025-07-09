streamlit.errors.StreamlitValueAssignmentNotAllowedError: This app has encountered an error. The original error message is redacted to prevent data leaks. Full error details have been recorded in the logs (if you're on Streamlit Cloud, click on 'Manage app' in the lower right of your app).

Traceback:
File "/mount/src/quotegenx2/app.py", line 229, in <module>
    st.file_uploader(
    ~~~~~~~~~~~~~~~~^
        "Upload supplier documents", type=['pdf', 'txt'], accept_multiple_files=True,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        key='file_uploader_state'
        ^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
File "/home/adminuser/venv/lib/python3.13/site-packages/streamlit/runtime/metrics_util.py", line 443, in wrapped_func
    result = non_optional_func(*args, **kwargs)
File "/home/adminuser/venv/lib/python3.13/site-packages/streamlit/elements/widgets/file_uploader.py", line 407, in file_uploader
    return self._file_uploader(
           ~~~~~~~~~~~~~~~~~~~^
        label=label,
        ^^^^^^^^^^^^
    ...<10 lines>...
        ctx=ctx,
        ^^^^^^^^
    )
    ^
File "/home/adminuser/venv/lib/python3.13/site-packages/streamlit/elements/widgets/file_uploader.py", line 440, in _file_uploader
    check_widget_policies(
    ~~~~~~~~~~~~~~~~~~~~~^
        self.dg,
        ^^^^^^^^
    ...<3 lines>...
        writes_allowed=False,
        ^^^^^^^^^^^^^^^^^^^^^
    )
    ^
File "/home/adminuser/venv/lib/python3.13/site-packages/streamlit/elements/lib/policies.py", line 177, in check_widget_policies
    check_session_state_rules(
    ~~~~~~~~~~~~~~~~~~~~~~~~~^
        default_value=default_value, key=key, writes_allowed=writes_allowed
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
File "/home/adminuser/venv/lib/python3.13/site-packages/streamlit/elements/lib/policies.py", line 83, in check_session_state_rules
    raise StreamlitValueAssignmentNotAllowedError(key=key
