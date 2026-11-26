"""Cấu hình chung. Sửa file này để đổi nhóm, chủ đề, từ khoá, tiêu chí chấm điểm."""

# Nhóm Telegram, trang báo, người theo dõi: lưu trong database, sửa trên web (mục "Cài đặt nguồn").

# Chủ đề cố định.
#   keywords: viết KHÔNG dấu, chữ thường; so với tin nhắn đã bỏ dấu.
#   exact:    so nguyên văn (giữ dấu, không phân biệt hoa thường) cho từ dễ nhầm khi bỏ dấu,
#             ví dụ "long" (bỏ dấu "lòng" cũng thành "long"), "vàng"/"vang".
TOPICS = {
    "crypto": {
        "label": "Crypto",
        "keywords": [
            "btc", "bitcoin", "eth", "ethereum", "solana", "bnb", "xrp", "token", "coin",
            "altcoin", "memecoin", "meme coin", "airdrop", "listing", "list san", "binance",
            "okx", "bybit", "bitget", "gate.io", "mexc", "coinbase", "defi", "nft", "dex",
            "futures", "stablecoin", "usdt", "usdc",
            "presale", "staking", "farm", "launchpad", "onchain", "whale", "ca:", "contract",
            "uniswap", "pancake", "raydium", "jupiter", "etf", "halving", "vi lanh",
        ],
        "exact": ["long", "short", "pump", "dump", "x2", "x10", "x100"],
    },
    "chung_khoan": {
        "label": "Chứng khoán",
        "keywords": [
            "chung khoan", "co phieu", "vn-index", "vnindex", "vn30", "hose", "hnx", "upcom",
            "khoi ngoai", "tu doanh", "margin", "co tuc", "niem yet", "thanh khoan san",
            "nasdaq", "s&p", "s&p 500", "dow jones", "nikkei", "phien sang", "phien chieu",
            "chot loi", "bat day", "ma ck",
        ],
        "exact": ["ATO", "ATC", "cp"],
    },
    "kinh_te": {
        "label": "Kinh tế trong & ngoài nước",
        "keywords": [
            "kinh te", "gdp", "cpi", "pce", "lam phat", "xuat khau", "nhap khau", "thue quan",
            "tariff", "ty gia", "dxy", "gia dau", "dau tho", "fdi", "suy thoai",
            "viec lam", "nfp", "non-farm", "that nghiep", "tang truong", "ngan sach",
            "trung quoc", "thuong mai", "bat dong san",
        ],
        "exact": ["vàng", "Mỹ", "EU"],
    },
    "lai_suat": {
        "label": "Lãi suất",
        "keywords": [
            "lai suat", "fed", "fomc", "nhnn", "ngan hang nha nuoc", "rate cut", "rate hike",
            "cat giam", "tang lai", "giam lai", "bps", "diem co ban", "trai phieu", "loi suat",
            "ecb", "boj", "pboc", "dot plot", "lai suat dieu hanh", "omo", "tin phieu",
        ],
    },
    "hop_bao": {
        "label": "Họp báo",
        "keywords": [
            "hop bao", "press conference", "phat bieu", "powell", "thong doc", "lagarde",
            "ueda", "cong bo", "ama", "livestream", "dai hoi co dong", "dhcd", "phien dieu tran",
            "bo tai chinh", "chinh phu",
        ],
    },
}

# Mục "Theo dõi": tin về chain mới, launchpad mới (so từ khoá giống TOPICS).
WATCH = {
    "chain_moi": {
        "label": "Chain mới",
        "keywords": [
            "mainnet", "testnet", "devnet", "chain moi", "blockchain moi", "layer 1", "layer 2", "layer1", "layer2",
            "ra mat chain", "launch mainnet", "chain id", "rpc", "rollup", "appchain", "evm compatible",
            "bridge sang", "incentivized testnet", "chay node",
        ],
        "exact": ["L1", "L2"],
    },
    "launchpad": {
        "label": "Launchpad mới",
        "keywords": [
            "launchpad", "launchpool", "megadrop", "ido", "ico", "ieo", "presale", "pre-sale", "fair launch",
            "fairlaunch", "public sale", "private sale", "seed round", "whitelist", "pinksale", "dao maker",
            "polkastarter", "fjord", "hodler airdrop", "tge", "san launch",
        ],
        "exact": ["WL"],
    },
}

# Người cần theo dõi: mọi tin của họ đều hiện ở mục "Theo dõi", kể cả khi không thuộc chủ đề nào.
# Ghi username (không có @), hoặc ID số, hoặc tên hiển thị đúng như trong nhóm.
WATCH_SENDERS = []  # thêm trên web; danh sách ở đây được gộp thêm

# Mục Link: bỏ các trang tra cứu blockchain / biểu đồ giá (CA đã có ở bảng token)
LINK_SKIP_DOMAINS = ["solscan.io", "dexscreener.com", "bscscan.com", "etherscan.io", "basescan.org",
                     "arbiscan.io", "tronscan.org", "tonviewer.com", "pump.fun", "gmgn.ai", "birdeye.so", "dextools.io"]

# Mục hiển thị trên web (menu bên trái). AI xếp mỗi sự kiện vào đúng 1 mục.
SECTIONS = {
    "kinh_te_vn": "Kinh tế trong nước",
    "kinh_te_qt": "Kinh tế ngoài nước",
    "chung_khoan": "Chứng khoán",
    "crypto": "Crypto",
}
SECTION_HINTS = """
- kinh_te_vn: kinh tế Việt Nam, NHNN, lãi suất/tỷ giá/giá vàng trong nước, chính sách của Chính phủ, Bộ Tài chính.
- kinh_te_qt: kinh tế thế giới, Fed/ECB/BOJ, CPI/NFP Mỹ, giá dầu, vàng thế giới, DXY, thuế quan, Trung Quốc, EU.
- chung_khoan: thị trường chứng khoán (VN-Index, cổ phiếu, khối ngoại, chứng khoán Mỹ/châu Á).
- crypto: tiền mã hoá, token, sàn, DeFi, airdrop, launchpad, chain.
"""
# Nhãn phụ gắn thêm cho sự kiện (một sự kiện có thể có 0, 1 hoặc 2 nhãn)
TAGS = {"lai_suat": "Lãi suất", "hop_bao": "Họp báo"}

# Tiêu chí chấm mức độ quan trọng (1-5) gửi cho AI. Sửa tuỳ ý.
IMPORTANCE_RULES = """
5 = Tác động lớn, cần biết ngay: quyết định lãi suất của Fed/NHNN/ECB/BOJ; số liệu CPI, NFP, GDP lệch dự báo;
    họp báo của Chủ tịch Fed hoặc Thống đốc NHNN; sàn lớn bị hack hoặc ngừng rút; ETF crypto được duyệt/từ chối;
    VN-Index hoặc BTC biến động trên 3% trong ngày; token được nhiều nhóm cùng nhắc và có thanh khoản trên 500.000 USD.
4 = Quan trọng: lịch họp báo/sự kiện vĩ mô sắp diễn ra; sàn lớn niêm yết token; khối ngoại mua/bán ròng mạnh;
    chính sách thuế quan, tỷ giá; token mới có thanh khoản trên 100.000 USD được nhắc nhiều lần.
3 = Đáng chú ý: phân tích, nhận định có số liệu; tin doanh nghiệp niêm yết; airdrop/launchpad có nguồn rõ.
2 = Tham khảo: nhận định cá nhân, tin nhỏ.
1 = Tin đồn không nguồn, quảng cáo, kêu gọi mua (shill) không có dữ liệu.
"""

# Yêu cầu riêng của bạn (thêm dần theo từng tình huống). AI sẽ làm theo khi tóm tắt.
CUSTOM_INSTRUCTIONS = """
- Viết tiếng Việt, ngắn gọn, mỗi ý một gạch đầu dòng, có con số cụ thể nếu tin gốc có.
- Gộp các tin nói về cùng một sự kiện thành MỘT mục, nêu ý chính.
- Không bịa thông tin ngoài tin nhắn được cung cấp.
- Tin về token: KHÔNG chép lại địa chỉ CA, giá, vốn hoá, thanh khoản (web đã có bảng Token riêng lấy số liệu mới nhất).
  Thay vào đó nêu: token gì, nhóm/người nào nhắc, bao nhiêu lần, diễn biến chính, dấu hiệu rủi ro (thanh khoản thấp, rút LP, dev xả).
- Nếu các tin đưa số liệu mâu thuẫn, chỉ dùng số của tin MỚI NHẤT và ghi kèm giờ.
- Tin báo giá tự động (bot báo tăng/giảm %) của token meme: tối đa 2 điểm, trừ khi nhiều người thật cùng bàn luận.
"""

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]  # thử lần lượt; tự dò model khác nếu cả hai ngừng hoạt động
MAX_CHARS_PER_CALL = 120_000
# Dự phòng khi Gemini hết hạn mức: Groq (miễn phí, key ở console.groq.com). Giới hạn token/phút thấp nên gửi đoạn ngắn hơn.
GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]  # model ngừng hoạt động sẽ tự dò model khác
GROQ_MAX_CHARS = 18_000  # giới hạn ký tự mỗi lần gọi AI (khoảng 40k token)
