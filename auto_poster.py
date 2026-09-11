import os, json, random, re, time, hmac, hashlib, base64, urllib.parse, datetime, requests
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

SITE_DOMAIN = "season.enjoy-onepage.com"
SITE_NAME = "시즌 가전솔루션"
ADSENSE_CLIENT = "ca-pub-2228289204702106"
ADSENSE_SLOT = "2231432699"

NAVER_CUSTOMER_ID = os.getenv('NAVER_CUSTOMER_ID', '1560667')
NAVER_ACCESS_LICENSE = os.getenv('NAVER_ACCESS_LICENSE', '0100000000275b3c8ab39dd56bad01b6c00904dfb52a7b55ec7176e7e42c48521f51cc0117')
NAVER_SECRET_KEY = os.getenv('NAVER_SECRET_KEY', 'AQAAAAAnWzyKs53Va60BtsAJBN+19kZUXy+tl4BrNzcRhWmIWw==')
COUPANG_ACCESS_KEY = os.getenv('COUPANG_ACCESS_KEY', 'd3f6de56-bd4a-4282-823f-a2d5f7a1898f')
COUPANG_SECRET_KEY = os.getenv('COUPANG_SECRET_KEY', 'dad5117274fc82084ad8276ca91e1cc465483134')

api_keys_str = os.getenv("GEMINI_API_KEY", "")
if not api_keys_str:
    print("Critical: GEMINI_API_KEY is not set.")
    exit(1)

API_KEYS = [k.strip() for k in api_keys_str.split(',') if k.strip()]
MODELS = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-1.5-flash']

def generate_with_retry(prompt, is_json=False):
    for key in API_KEYS:
        genai.configure(api_key=key)
        for model_name in MODELS:
            try:
                model = genai.GenerativeModel(model_name)
                config = genai.GenerationConfig(response_mime_type="application/json") if is_json else None
                res = model.generate_content(prompt, generation_config=config)
                if res.text and res.text.strip():
                    text = res.text.strip()
                    if is_json:
                        text = text.replace('```json', '').replace('```', '').strip()
                    return text
            except Exception as e:
                print(f"Fallback triggered: Failed on {model_name} with key ...{key[-4:]} -> {e}")
                time.sleep(1)
                continue
    raise Exception("Critical: Failed to generate content from all Gemini models!")

def get_naver_signature(timestamp, method, path):
    message = f"{timestamp}.{method}.{path}"
    sign = hmac.new(NAVER_SECRET_KEY.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(sign.digest()).decode()

def get_trending_keywords(hint_keyword):
    path = '/keywordstool'
    url = 'https://api.naver.com' + path
    timestamp = str(int(round(time.time() * 1000)))
    headers = {
        'X-Timestamp': timestamp,
        'X-API-KEY': NAVER_ACCESS_LICENSE,
        'X-Customer': str(NAVER_CUSTOMER_ID),
        'X-Signature': get_naver_signature(timestamp, 'GET', path)
    }
    try:
        response = requests.get(url, params={'hintKeywords': hint_keyword, 'showDetail': 1}, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            kw_list = []
            for item in data.get('keywordList', []):
                rel_kw = item.get('relKeyword', '').strip()
                if not rel_kw:
                    continue
                pc_qc = item.get('monthlyPcQcCnt', 0)
                mo_qc = item.get('monthlyMobileQcCnt', 0)
                pc_cnt = int(pc_qc) if str(pc_qc).isdigit() else 10
                mo_cnt = int(mo_qc) if str(mo_qc).isdigit() else 10
                total_qc = pc_cnt + mo_cnt
                kw_list.append({'keyword': rel_kw, 'volume': total_qc})
            return kw_list
    except Exception as e:
        print(f"Naver API error: {e}")
    return []

def get_coupang_signature(method, url_path):
    from time import gmtime, strftime
    datetime_gmt = strftime('%y%m%d', gmtime()) + 'T' + strftime('%H%M%S', gmtime()) + 'Z'
    path, *query_parts = url_path.split("?")
    query = query_parts[0] if query_parts else ""
    message = datetime_gmt + method + path + query
    signature = hmac.new(bytes(COUPANG_SECRET_KEY, "utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, signed-date={datetime_gmt}, signature={signature}"

def search_coupang_products(keyword, limit=3):
    method = 'GET'
    url_path = f"/v2/providers/affiliate_open_api/apis/openapi/products/search?keyword={urllib.parse.quote(keyword)}&limit={limit}"
    url = f"https://api-gateway.coupang.com{url_path}"
    headers = {"Authorization": get_coupang_signature(method, url_path), "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get('data', {}).get('productData', [])
    except Exception as e:
        print(f"Coupang API error: {e}")
    return []

def generate_spec_review(keyword, products):
    p1 = products[0]
    p2 = products[1] if len(products) > 1 else p1
    p3 = products[2] if len(products) > 2 else p2

    prompt = f"""당신은 노써치(Nosearch) 및 뉴욕타임스 와이어커터(Wirecutter) 수준의 대한민국 최상위 테크/가전 리뷰 수석 에디터입니다.
구글 공식 'Google Search Reviews System' 가이드라인을 완벽히 충족하는 3-Pick 스펙 비교 가이드 본문을 작성하세요.

주제 키워드: {keyword}

선정된 후보 제품 3종:
[후보 1 (종합 1위/국민템)]
- 상품명: {p1.get('productName')}
- 가격: {p1.get('productPrice', '')}원
[후보 2 (가성비 추천)]
- 상품명: {p2.get('productName')}
- 가격: {p2.get('productPrice', '')}원
[후보 3 (하이엔드/프리미엄)]
- 상품명: {p3.get('productName')}
- 가격: {p3.get('productPrice', '')}원

[작성 필수 규칙]
1. 제목: 2026년 {keyword} 추천 TOP 3 스펙 비교 및 구매 가이드 (마크다운 H1 # 제목 출력 금지, 본문 바로 시작)
2. 첫 3문장: 서론을 길게 쓰지 말고, 바쁜 현대인을 위해 왜 이 3개 모델로 압축했는지 핵심 결론 선제시.
3. 3초 요약 박스 (HTML <div class="summary-box">): 1위 국민템, 2위 가성비, 3위 프리미엄을 각각 1줄로 규정.
4. 구글 Reviews System 필수 충족:
   - 구매 전 반드시 체크해야 할 스펙 기준 3가지 (정량적 수치 포함: 소음 dB, 소비전력 W, 소재 등)
   - 3개 모델의 심층 분석 섹션 작성: 각 모델마다 반드시 '👍 장점 2가지'와 '⚠️ 솔직한 단점/아쉬운 점 1가지(Cons)'를 명시할 것.
   - 단점이 솔직하게 들어가야 구글 AI 필터를 통과하고 소비자 신뢰도가 극대화됩니다.
5. 중간 링크 마커: 각 제품 심층 분석 문단 끝에 단독 줄로 정확히 '<!-- CTA_BUTTON_1 -->', '<!-- CTA_BUTTON_2 -->', '<!-- CTA_BUTTON_3 -->'를 1개씩 삽입할 것.
6. 스펙 비교표 데이터: 본문 중간에 3개 제품의 [포지셔닝 | 가격대 | 핵심스펙 2가지 | 추천대상]을 비교하는 마크다운 테이블을 반드시 포함할 것.
7. 말투: 상업적 광고 느낌을 철저히 배제하고, 차분하고 전문적인 엔지니어/에디터의 객관적 분석 톤 유지.
8. 분량: 공백 제외 2,000자 내외.
"""
    return generate_with_retry(prompt)

def create_hero_thumbnail(title_text, output_path):
    w, h = 1200, 675
    img = Image.new("RGB", (w, h), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    for y in range(h):
        r = int(15 + (y / h) * 15)
        g = int(23 + (y / h) * 20)
        b = int(42 + (y / h) * 35)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    draw.rounded_rectangle([60, 60, 220, 110], radius=8, fill=(37, 99, 235))
    
    font_path = "NanumGothic-Bold.ttf"
    if not os.path.exists(font_path):
        font_path = r"c:\Windows\Fonts\malgunbd.ttf" if os.path.exists(r"c:\Windows\Fonts\malgunbd.ttf") else None

    try:
        font_logo = ImageFont.truetype(font_path, 24) if font_path else ImageFont.load_default()
        font_main = ImageFont.truetype(font_path, 52) if font_path else ImageFont.load_default()
        font_sub = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
    except:
        font_logo = font_main = font_sub = ImageFont.load_default()

    draw.text((80, 72), "SPEC REVIEW", fill=(255, 255, 255), font=font_logo)
    
    draw.text((60, 220), title_text, fill=(255, 255, 255), font=font_main)
    draw.text((60, 310), "2026 TOP 3 스펙 비교 & 구매 가이드", fill=(56, 189, 248), font=font_sub)
    draw.text((60, 560), f"⚡ {SITE_NAME} | {SITE_DOMAIN}", fill=(148, 163, 184), font=font_logo)

    img.save(output_path, "WEBP", quality=90)

def main():
    print(f"🚀 [{SITE_NAME}] 고전환 스펙비교 자동 포스팅 시작...")

    seed_file = "coupang_categories.txt"
    with open(seed_file, "r", encoding="utf-8") as f:
        seeds = [line.strip() for line in f if line.strip()]

    used_file = "used_keywords.txt"
    used_keywords = set()
    if os.path.exists(used_file):
        with open(used_file, "r", encoding="utf-8") as f:
            used_keywords = set(line.strip() for line in f if line.strip())

    random.shuffle(seeds)
    target_keyword = None

    for seed in seeds:
        metrics = get_trending_keywords(seed)
        if metrics:
            available = [m for m in metrics if m['keyword'] not in used_keywords]
            golden = [m for m in available if 500 <= m['volume'] <= 50000]
            if golden:
                golden.sort(key=lambda x: x['volume'], reverse=True)
                target_keyword = golden[0]['keyword']
                break
            elif available:
                target_keyword = available[0]['keyword']
                break
        if seed not in used_keywords:
            target_keyword = f"{seed} 추천"
            break

    if not target_keyword:
        target_keyword = f"{random.choice(seeds)} 추천"

    print(f"✨ 확정 타깃 키워드: [{target_keyword}]")

    products = search_coupang_products(target_keyword, limit=3)
    if not products or len(products) < 3:
        alt_products = search_coupang_products(target_keyword.replace(" 추천", ""), limit=3)
        if alt_products:
            products = alt_products

    while len(products) < 3:
        products.append({
            "productName": f"{target_keyword} 인기 검증 모델 {len(products)+1}",
            "productPrice": "최저가 확인",
            "productImage": "https://via.placeholder.com/300?text=Product",
            "productUrl": "https://www.coupang.com"
        })

    p1, p2, p3 = products[0], products[1], products[2]

    cards_html = f"""
<div class="pick-cards-wrap">
  <div class="pick-card">
    <div>
      <span class="pick-badge badge-gold">🥇 종합 1위 (국민 추천)</span>
      <img src="{p1.get('productImage', '')}" alt="{p1.get('productName')}" class="pick-img" onerror="this.src='https://images.unsplash.com/photo-1584438784894-089d6a62b8fa?w=300&q=80'">
      <div class="pick-name">{p1.get('productName')}</div>
      <div class="pick-price">{p1.get('productPrice', '')}원</div>
      <div class="pick-feature">실패 없는 대중적 선택, 리뷰 검증 최다</div>
    </div>
    <a href="{p1.get('productUrl')}" target="_blank" rel="nofollow noopener" class="btn-cta">최저가 & 로켓배송 확인하기</a>
  </div>
  <div class="pick-card">
    <div>
      <span class="pick-badge badge-silver">🥈 가성비 추천 (Best Value)</span>
      <img src="{p2.get('productImage', '')}" alt="{p2.get('productName')}" class="pick-img" onerror="this.src='https://images.unsplash.com/photo-1584438784894-089d6a62b8fa?w=300&q=80'">
      <div class="pick-name">{p2.get('productName')}</div>
      <div class="pick-price">{p2.get('productPrice', '')}원</div>
      <div class="pick-feature">핵심 기능 완비, 가격 거품 제거</div>
    </div>
    <a href="{p2.get('productUrl')}" target="_blank" rel="nofollow noopener" class="btn-cta">최저가 & 로켓배송 확인하기</a>
  </div>
  <div class="pick-card">
    <div>
      <span class="pick-badge badge-bronze">🥉 하이엔드 (Premium)</span>
      <img src="{p3.get('productImage', '')}" alt="{p3.get('productName')}" class="pick-img" onerror="this.src='https://images.unsplash.com/photo-1584438784894-089d6a62b8fa?w=300&q=80'">
      <div class="pick-name">{p3.get('productName')}</div>
      <div class="pick-price">{p3.get('productPrice', '')}원</div>
      <div class="pick-feature">최신 풀옵션 탑재, 최고 성능 지향</div>
    </div>
    <a href="{p3.get('productUrl')}" target="_blank" rel="nofollow noopener" class="btn-cta">최저가 & 재고 확인하기</a>
  </div>
</div>
"""

    review_body = generate_spec_review(target_keyword, products)

    btn1 = f'<div class="text-center my-6"><a href="{p1.get("productUrl")}" target="_blank" rel="nofollow noopener" class="btn-cta-mid">👉 {p1.get("productName")[:20]}... 최저가 및 카드할인 보기</a></div>'
    btn2 = f'<div class="text-center my-6"><a href="{p2.get("productUrl")}" target="_blank" rel="nofollow noopener" class="btn-cta-mid">👉 {p2.get("productName")[:20]}... 최저가 및 쿠폰 확인하기</a></div>'
    btn3 = f'<div class="text-center my-6"><a href="{p3.get("productUrl")}" target="_blank" rel="nofollow noopener" class="btn-cta-mid">👉 {p3.get("productName")[:20]}... 최저가 및 재고현황 보기</a></div>'

    review_body = review_body.replace("<!-- CTA_BUTTON_1 -->", btn1)
    review_body = review_body.replace("<!-- CTA_BUTTON_2 -->", btn2)
    review_body = review_body.replace("<!-- CTA_BUTTON_3 -->", btn3)

    adsense_html = f"""
<div class="ad-slot-wrap">
  <ins class="adsbygoogle"
       style="display:block"
       data-ad-client="{ADSENSE_CLIENT}"
       data-ad-slot="{ADSENSE_SLOT}"
       data-ad-format="auto"
       data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</div>
"""

    ftc_notice = """
<p style="font-size: 12px; color: #94a3b8; text-align: center; margin-top: 50px; margin-bottom: 20px;">
  이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.
</p>
"""

    final_content = cards_html + "\n\n" + review_body + "\n\n" + adsense_html + "\n\n" + ftc_notice

    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    ts = int(time.time())
    img_dir = os.path.join("assets", "images")
    os.makedirs(img_dir, exist_ok=True)
    thumb_name = f"thumb_{ts}.webp"
    thumb_path = os.path.join(img_dir, thumb_name)

    create_hero_thumbnail(target_keyword, thumb_path)

    post_title = f"2026년 {target_keyword} 추천 TOP 3 스펙 비교 및 구매 가이드"
    post_slug = f"{date_str}-{ts}"
    post_path = os.path.join("_posts", f"{post_slug}.md")
    os.makedirs("_posts", exist_ok=True)

    post_frontmatter = f"""---
layout: post
title: "{post_title}"
date: {now.strftime("%Y-%m-%d %H:%M:%S")} +0900
image: "/assets/images/{thumb_name}"
---

{final_content}
"""

    with open(post_path, "w", encoding="utf-8") as f:
        f.write(post_frontmatter)

    with open(used_file, "a", encoding="utf-8") as f:
        f.write(f"{target_keyword}\n")

    print(f"✅ 포스팅 생성 완료: {post_path}")

if __name__ == "__main__":
    main()
