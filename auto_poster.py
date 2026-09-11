import os, json, random, re, time, hmac, hashlib, base64, urllib.parse, datetime, requests
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

SITE_DOMAIN = "season.enjoy-onepage.com"
SITE_NAME = "시즌 가전솔루션"

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
MODELS = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite']

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

COUPANG_SUB_ID = "CloudflareSite"

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

def create_coupang_deeplinks(product_urls, sub_id=COUPANG_SUB_ID):
    if not product_urls:
        return []
    method = 'POST'
    url_path = '/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink'
    url = f"https://api-gateway.coupang.com{url_path}"
    headers = {"Authorization": get_coupang_signature(method, url_path), "Content-Type": "application/json"}
    body = {"coupangUrls": product_urls, "subId": sub_id}
    try:
        response = requests.post(url, headers=headers, json=body, timeout=10)
        if response.status_code == 200:
            items = response.json().get('data', [])
            return [item.get('shortenUrl') for item in items]
    except Exception as e:
        print(f"Coupang Deeplink error: {e}")
    return product_urls

def generate_spec_review(keyword, products):
    p1 = products[0]
    p2 = products[1] if len(products) > 1 else p1
    p3 = products[2] if len(products) > 2 else p2

    print("  ▶ [Pass 1/3] 3-Pick 스펙 비교 초안(Draft) 작성 중...")
    draft_prompt = f"""당신은 노써치(Nosearch) 및 와이어커터(Wirecutter) 수준의 대한민국 최상위 테크/가전 리뷰 수석 에디터입니다.
주제 키워드: {keyword}

후보 제품 3종:
1. 종합 1위/국민템: {p1.get('productName')} ({p1.get('productPrice', '')}원)
2. 가성비 추천: {p2.get('productName')} ({p2.get('productPrice', '')}원)
3. 하이엔드/프리미엄: {p3.get('productName')} ({p3.get('productPrice', '')}원)

위 3종을 바탕으로 다음 요소를 포함한 1차 초안을 작성하세요:
- 3초 요약 박스 (<div class="summary-box">)
- 구매 전 필수 체크 스펙 3가지 (정량적 수치 포함: dB, W, 용량 등)
- 제품별 상세 분석 (각 모델마다 장점 2개와 솔직한 단점 1개 명시)
- 핵심 스펙 6열 비교 마크다운 테이블
- 중간 링크 마커 '<!-- CTA_BUTTON_1 -->', '<!-- CTA_BUTTON_2 -->', '<!-- CTA_BUTTON_3 -->' 삽입
"""
    draft = generate_with_retry(draft_prompt)
    time.sleep(1)

    print("  ▶ [Pass 2/3] 구글 Reviews System 300점 기준 심층 비판 및 결함 분석(Critic) 중...")
    critic_prompt = f"""당신은 구글 공식 'Google Search Reviews System' 알고리즘 평가관이자 최고 수준의 팩트체커입니다.
아래 작성된 1차 초안을 엄격하게 심사하여 독자가 느끼는 신뢰도와 구매 결정에 방해되는 결함을 비판하고 분석하세요.

[초안 텍스트]
{draft}

[심사 및 지적 기준]
1. AI 특유의 판에 박힌 번역투, 공허한 미사여구, 무의미한 칭찬 반복 지적
2. 구체적인 수치(소음 dB, 출력 W, 실제 체감 용량, 재질 등) 없이 두루뭉술하게 설명된 부분 지적
3. 단점이 너무 무난하거나 칭찬 일색이라 신뢰도가 떨어지는 부분 지적 (치명적이거나 실제 사용자가 겪는 현실적 단점 요구)
4. 스펙 비교표의 가독성과 정보 완결성 지적
5. 마커 '<!-- CTA_BUTTON_1 -->', '<!-- CTA_BUTTON_2 -->', '<!-- CTA_BUTTON_3 -->' 보존 여부 확인

반드시 다음 JSON 형식으로만 답변하세요:
{{
  "ai_phrases_to_remove": ["제거하거나 수정할 AI 번역투/과장 문장들"],
  "specs_to_reinforce": ["더 구체적 수치나 팩트가 보강되어야 할 스펙 항목들"],
  "cons_criticism": "단점이 솔직하고 현실적인지, 어떻게 보강해야 신뢰도를 극대화할 수 있는지",
  "key_directives_for_pass3": ["Pass 3 재작성 시 반드시 반영해야 할 핵심 명령 3~5가지"]
}}
"""
    critique_json_str = generate_with_retry(critic_prompt, is_json=True)
    print(f"  🔍 결함 분석 완료 (지적 사항 반영 준비)")
    time.sleep(1)

    print("  ▶ [Pass 3/3] 비판 피드백 완벽 반영 및 최종 정밀 재작성(Final Rewrite) 중...")
    final_rewrite_prompt = f"""당신은 대한민국 최고 테크/가전 리뷰 수석 에디터입니다.
아래 [1차 초안]과 [Pass 2 심층 비판 리포트]를 완벽히 반영하여, 
독자가 읽었을 때 '진짜 가전 전문가가 직접 비교 분석한 신뢰도 100%의 원고'로 최종 재작성(Rewrite)하세요.

[1차 초안]
{draft}

[Pass 2 심층 비판 리포트]
{critique_json_str}

[필수 최종 작성 규칙]
1. 제목이나 마크다운 H1 (#) 태그는 절대 출력하지 마세요. 바로 본문 첫 문장으로 시작하세요.
2. 첫 3문장: 바쁜 현대인을 위해 왜 이 3개 모델로 압축했는지 핵심 결론을 직관적으로 선제시하세요.
3. 3초 요약 박스 (<div class="summary-box">): 1위 국민템, 2위 가성비, 3위 프리미엄을 각각 1줄로 명확히 규정하세요.
4. Pass 2 비판 반영:
   - 비판 리포트에서 지적된 번역투/뻔한 칭찬을 완전히 삭제하세요.
   - 구매 전 체크해야 할 스펙 기준 3가지를 정량적 수치와 함께 전문적으로 설명하세요.
   - 3개 모델 분석 시 '👍 장점 2가지'와 '⚠️ 솔직한 단점/아쉬운 점 1가지'를 명확하고 날카롭게 작성하세요. 솔직한 단점이어야 구글 AI 필터를 통과합니다.
5. 중간 링크 마커: 각 제품 설명 직후 단독 줄로 반드시 '<!-- CTA_BUTTON_1 -->', '<!-- CTA_BUTTON_2 -->', '<!-- CTA_BUTTON_3 -->'를 1회씩 그대로 유지하세요.
6. 스펙 비교표: 3개 제품의 [포지셔닝 | 상품명 | 가격대 | 핵심스펙 1 | 핵심스펙 2 | 추천대상] 6열 마크다운 테이블을 완벽하게 완성하세요.
7. 분량 및 톤앤매너: 2,000자 내외의 전문적이고 객관적이며 설득력 있는 어조를 유지하세요.
"""
    final_review = generate_with_retry(final_rewrite_prompt)
    final_review = re.sub(r'(?im)^(#+\s*)H[234][:\s.]*\s*', r'\1', final_review)
    final_review = re.sub(r'^---.*?---\s*', '', final_review, flags=re.DOTALL)
    return final_review

def create_hero_thumbnail(title_text, output_path):
    w, h = 1200, 420
    img = Image.new("RGB", (w, h), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    # 테크 프리미엄 배경 그라데이션
    for y in range(h):
        r = int(15 + (y / h) * 12)
        g = int(23 + (y / h) * 25)
        b = int(42 + (y / h) * 50)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    font_path = "NanumGothic-Bold.ttf"
    if not os.path.exists(font_path):
        font_path = r"c:\Windows\Fonts\malgunbd.ttf" if os.path.exists(r"c:\Windows\Fonts\malgunbd.ttf") else None

    try:
        font_badge = ImageFont.truetype(font_path, 20) if font_path else ImageFont.load_default()
        font_main = ImageFont.truetype(font_path, 60) if font_path else ImageFont.load_default()
        font_sub = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
        font_tag = ImageFont.truetype(font_path, 22) if font_path else ImageFont.load_default()
    except:
        font_badge = font_main = font_sub = font_tag = ImageFont.load_default()

    # 1. 상단 뱃지 2종
    draw.rounded_rectangle([60, 40, 220, 85], radius=8, fill=(37, 99, 235))
    draw.text((75, 52), "SPEC REVIEW", fill=(255, 255, 255), font=font_badge)

    draw.rounded_rectangle([235, 40, 430, 85], radius=8, fill=(30, 41, 59), outline=(56, 189, 248), width=1)
    draw.text((250, 52), "2026 OFFICIAL PICK", fill=(56, 189, 248), font=font_badge)

    # 우측 상단 브랜드 워터마크
    draw.text((820, 52), f"⚡ {SITE_NAME} | 2026 큐레이션", fill=(148, 163, 184), font=font_badge)

    # 2. 메인 키워드 타이틀
    draw.text((60, 115), title_text, fill=(255, 255, 255), font=font_main)

    # 3. 서브 카피 (간격 밀착)
    draw.text((60, 200), "실구매자 평점 & 300점 스펙 데이터 기반 TOP 3 실측 비교", fill=(56, 189, 248), font=font_sub)

    # 4. 하단 3대 검증 박스
    draw.rounded_rectangle([60, 265, 390, 335], radius=10, fill=(30, 41, 59), outline=(71, 85, 105), width=1)
    draw.text((95, 285), "단점 & 누진세 검증", fill=(226, 232, 240), font=font_tag)

    draw.rounded_rectangle([415, 265, 745, 335], radius=10, fill=(30, 41, 59), outline=(71, 85, 105), width=1)
    draw.text((450, 285), "가성비 vs 프리미엄", fill=(226, 232, 240), font=font_tag)

    draw.rounded_rectangle([770, 265, 1100, 335], radius=10, fill=(30, 41, 59), outline=(71, 85, 105), width=1)
    draw.text((805, 285), "카드할인 & 쿠폰 혜택", fill=(226, 232, 240), font=font_tag)

    # 5. 하단 도메인
    draw.text((60, 365), f"{SITE_DOMAIN} | 독립적 데이터 스펙 비교 분석실", fill=(100, 116, 139), font=font_badge)

    img.save(output_path, "WEBP", quality=90)

def main():
    print(f"🚀 [{SITE_NAME}] 고전환 스펙비교 자동 포스팅 시작...")

    seed_file = "coupang_categories.txt"
    with open(seed_file, "r", encoding="utf-8") as f:
        seeds = [line.strip() for line in f if line.strip()]

    used_file = "used_keywords.txt"
    used_keywords_list = []
    if os.path.exists(used_file):
        with open(used_file, "r", encoding="utf-8") as f:
            used_keywords_list = [line.strip() for line in f if line.strip()]
    used_keywords_set = set(used_keywords_list)

    random.shuffle(seeds)
    target_keyword = None
    all_candidate_metrics = []

    # 1단계: 미사용 황금 키워드 우선 탐색
    for seed in seeds:
        metrics = get_trending_keywords(seed)
        if metrics:
            all_candidate_metrics.extend(metrics)
            available = [m for m in metrics if m['keyword'] not in used_keywords_set]
            golden = [m for m in available if 500 <= m['volume'] <= 50000]
            if golden:
                golden.sort(key=lambda x: x['volume'], reverse=True)
                target_keyword = golden[0]['keyword']
                break
            elif available:
                target_keyword = available[0]['keyword']
                break
        if seed not in used_keywords_set:
            target_keyword = f"{seed} 추천"
            break

    # 2단계: 모든 키워드가 소진된 경우 (FIFO 자연 순환)
    if not target_keyword:
        print("ℹ️ 모든 키워드 풀 1회 소진 확인: 가장 오래전에 작성된 키워드부터 자연 순환(FIFO) 발동")
        if used_keywords_list:
            target_keyword = used_keywords_list[0]
        else:
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

    # 쿠팡 공식 딥링크 API로 단축링크 및 subId=CloudflareSite 강제 적용
    raw_urls = [p.get('productUrl') for p in products]
    short_urls = create_coupang_deeplinks(raw_urls, sub_id=COUPANG_SUB_ID)
    for idx, short_url in enumerate(short_urls):
        if short_url:
            products[idx]['productUrl'] = short_url
            print(f"  🔗 쿠팡 딥링크 변환 완료 [{idx+1}위]: {short_url} (subId={COUPANG_SUB_ID})")

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


    guide_banner = f"""
<div style="background: linear-gradient(135deg, #f8fafc 0%, #eff6ff 100%); border: 1px solid #bfdbfe; border-left: 5px solid #2563eb; border-radius: 0.75rem; padding: 1.25rem 1.5rem; margin: 2rem 0; box-shadow: 0 2px 4px rgba(0,0,0,0.03);">
  <p style="margin: 0 0 0.5rem 0; font-weight: 800; color: #1e3a8a; font-size: 1.05rem;">📖 {SITE_NAME} 공식 가이드북 안내</p>
  <p style="margin: 0 0 0.75rem 0; font-size: 0.95rem; color: #334155; line-height: 1.6;">본 포스팅의 세부 분석 외에, 실패 없는 선택 기준과 핵심 체크리스트를 집대성한 종합 가이드를 확인해보세요.</p>
  <a href="/guide/" style="display: inline-block; background: #2563eb; color: #ffffff !important; font-weight: 700; font-size: 0.9rem; padding: 0.5rem 1rem; border-radius: 0.5rem; text-decoration: none;">👉 {SITE_NAME} 2026 공식 가이드북 보러가기</a>
</div>
"""

    ftc_notice = """
<p style="font-size: 12px; color: #94a3b8; text-align: center; margin-top: 50px; margin-bottom: 20px;">
  이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.
</p>
"""

    # 광고는 _layouts/post.html 레이아웃에서 관리 (위치 변경 시 레이아웃 파일만 수정)
    final_content = cards_html + "\n\n" + review_body + "\n\n" + guide_banner + "\n\n" + ftc_notice

    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    ts = int(time.time())
    img_dir = os.path.join("assets", "images")
    os.makedirs(img_dir, exist_ok=True)
    thumb_name = f"thumb_{ts}.webp"
    thumb_path = os.path.join(img_dir, thumb_name)

    create_hero_thumbnail(target_keyword, thumb_path)

    post_title = f"2026년 {target_keyword} 추천 TOP 3 스펙 비교 및 구매 가이드"
    clean_kw = re.sub(r'[^\w\s-]', '', target_keyword).strip()
    safe_slug = re.sub(r'[-\s]+', '-', clean_kw)
    post_slug = f"{date_str}-{safe_slug}"
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

    # used_keywords.txt 관리 (FIFO: 사용한 키워드는 항상 최하단으로 갱신)
    updated_used = [k for k in used_keywords_list if k != target_keyword]
    updated_used.append(target_keyword)
    with open(used_file, "w", encoding="utf-8") as f:
        for kw in updated_used:
            f.write(f"{kw}\n")

    print(f"✅ 포스팅 생성 완료: {post_path}")

if __name__ == "__main__":
    main()
