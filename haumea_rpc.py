from __future__ import annotations


def is_file_reference_error(e: Exception) -> bool:
    try:
        from telethon.errors.rpcerrorlist import (
            FileReferenceExpiredError,
            FileReferenceInvalidError,
            FileReferenceEmptyError,
        )
        if isinstance(e, (FileReferenceExpiredError, FileReferenceInvalidError, FileReferenceEmptyError)):
            return True
    except Exception:
        pass

    err_l = str(e).lower()
    e_name = type(e).__name__.lower()
    return ("file reference" in err_l) or ("file_reference" in err_l) or ("filereference" in e_name)


def is_self_destructing_media_error(e: Exception) -> bool:
    err_l = str(e).lower()
    return ("ttl" in err_l) or ("ttl_seconds" in err_l) or ("ttl-period" in err_l)
