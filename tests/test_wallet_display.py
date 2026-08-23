from app.services.wallet_display import mask_wallet_address


def test_masks_a_full_address():
    addr = "0xAbCdEf1234567890AbCdEf1234567890AbCdEf12"
    assert mask_wallet_address(addr) == "0xAbCd...dEf12"


def test_leaves_short_strings_unchanged():
    assert mask_wallet_address("sample") == "sample"
    assert mask_wallet_address("") == ""


def test_boundary_length_ten_is_unchanged_eleven_is_masked():
    ten = "0x12345678"  # len 10
    eleven = "0x123456789"  # len 11
    assert mask_wallet_address(ten) == ten
    assert mask_wallet_address(eleven) == f"{eleven[:6]}...{eleven[-5:]}"
