from curl_cffi import requests
import time
import logging
import json
import os
from datetime import datetime

# Ürün Katalog İçin API
# https://apigw.trendyol.com/discovery-sfint-search-service/api/search/products/?pi=2&pathModel=erbatab-x-b166925&isOpenFilterEnabled=true&channelId=1&culture=tr-TR&sst=PRICE_BY_ASC


# Fotoğraflı Yorumlar için API 
# https://apigw.trendyol.com/discovery-storefront-trproductgw-service/api/review-read/product-reviews/images?channelId=1&listingId=1f919e492999b36448b72cc68a31b958&contentId=467921164&merchantId=679772&page=0&order=DESC&orderBy=LastModifiedDate


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TrendyolBatchScraper:
    def __init__(self):
        self.base_url = "https://apigw.trendyol.com/discovery-storefront-trproductgw-service/api/review-read/product-reviews/images"
        self.session = requests.Session(impersonate="chrome120")
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://www.trendyol.com",
            "Referer": "https://www.trendyol.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site"
        })
        self.all_reviews_dict = {} 

    @staticmethod
    def _mask_fullname(fullname):
        """İsimleri KVKK standartlarında maskeler. (Örn: Ahmet Yılmaz -> A**** Y****)"""
        if not fullname:
            return ""
        
        words = str(fullname).strip().split()
        masked_words = []
        
        for word in words:
            if all(char == '*' for char in word):
                masked_words.append(word)
            elif len(word) > 1:
                masked_words.append(word[0] + '*' * (len(word) - 1))
            else:
                masked_words.append(word)
                
        return " ".join(masked_words)

    def get_total_pages(self, params):
        try:
            response = self.session.get(self.base_url, params=params, timeout=15)
            if response.status_code != 200:
                logging.error(f"HTTP Hatası: {response.status_code} - API Gateway reddetti.")
                return 0
            
            data = response.json()
            return data.get("totalPages", 0)
        except Exception as e:
            logging.error(f"Toplam sayfa sayısı alınamadı: {e}")
            return 0

    def process_catalog(self, catalog, max_pages_per_product=10):
        total_products = len(catalog)
        current_product_index = 1

        for product_name, ids in catalog.items():
            logging.info(f"--- İşleniyor ({current_product_index}/{total_products}): {product_name} ---")
            
            params = {
                "channelId": 1,
                "listingId": ids["listingId"],
                "contentId": ids["contentId"],
                "merchantId": ids["merchantId"],
                "page": 0,
                "order":"DESC",
                "orderBy":"LastModifiedDate"
            }

            actual_total_pages = self.get_total_pages(params)
            pages_to_fetch = min(actual_total_pages, max_pages_per_product)
            
            if pages_to_fetch == 0:
                logging.warning(f"{product_name} için hiç yorum sayfası bulunamadı. Atlanıyor.")
                current_product_index += 1
                continue

            for page in range(pages_to_fetch):
                params["page"] = page
                
                try:
                    response = self.session.get(self.base_url, params=params, timeout=15)
                    
                    if response.status_code == 429:
                        logging.warning("Rate limit tetiklendi! 10 saniye uyutuluyor...")
                        time.sleep(10)
                        continue
                    elif response.status_code != 200:
                        logging.error(f"Sayfa {page} başarısız. Kodu: {response.status_code}")
                        continue

                    data = response.json()
                    content = data.get("content", [])
                    
                    for item in content:
                        review_id = item.get("reviewId")
                        if not review_id:
                            continue 

                        media_url = item.get("mediaFile", {}).get("url", "") if item.get("mediaFile") else ""
                        
                        if review_id not in self.all_reviews_dict:
                            raw_date = item.get("lastModifiedDate")
                            formatted_date = datetime.fromtimestamp(raw_date / 1000.0).isoformat() if raw_date else None
                            
                            masked_name = self._mask_fullname(item.get("userFullName"))
                            
                            self.all_reviews_dict[review_id] = {
                                "ProductName": product_name, 
                                "ReviewID": review_id,
                                "UserFullName": masked_name,
                                "Rate": item.get("rate"),
                                "Comment": item.get("comment"),
                                "Trusted": item.get("trusted"),
                                "SellerName": item.get("sellerName"),
                                "MediaURLs": [media_url] if media_url else [],
                                "LastModifiedDate": formatted_date
                            }
                        else:
                            if media_url and media_url not in self.all_reviews_dict[review_id]["MediaURLs"]:
                                self.all_reviews_dict[review_id]["MediaURLs"].append(media_url)
                    
                    logging.info(f"{product_name} -> Sayfa {page + 1}/{pages_to_fetch} çekildi.")
                    time.sleep(0.5) 
                    
                except Exception as e:
                    logging.error(f"{product_name} Sayfa {page} hatası: {e}")
                    continue
            
            if current_product_index < total_products:
                time.sleep(3)
                
            current_product_index += 1

    def export_to_json(self, filename="toplu_trendyol_yorumlari.json"):
        if not self.all_reviews_dict:
            logging.warning("Dışa aktarılacak hiçbir veri toplanamadı.")
            return

        try:
            final_json_array = list(self.all_reviews_dict.values())
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(final_json_array, f, ensure_ascii=False, indent=4)
            logging.info(f"Mükemmel! {len(final_json_array)} adet anonimleştirilmiş yorum '{filename}' dosyasına yazıldı.")
        except IOError as e:
            logging.error(f"JSON dosyası yazılırken hata oluştu: {e}")


if __name__ == "__main__":
    
    CATALOG_FILE = "urun_katalog.json"
    
    if not os.path.exists(CATALOG_FILE):
        logging.error(f"Kritik Hata: '{CATALOG_FILE}' dosyası bulunamadı. Lütfen script ile aynı dizinde olduğundan emin ol.")
        exit(1)
        
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            PRODUCT_CATALOG = json.load(f)
    except json.JSONDecodeError:
        logging.error(f"Kritik Hata: '{CATALOG_FILE}' dosyası geçerli bir JSON formatında değil. Virgül veya parantez hatası olabilir.")
        exit(1)

    logging.info(f"{len(PRODUCT_CATALOG)} adet ürün kataloğa yüklendi. Motor çalışıyor...")
    scraper = TrendyolBatchScraper()

    # Burada her ürün için kaç page çekilecek belirtilmeli
    scraper.process_catalog(PRODUCT_CATALOG, max_pages_per_product=1)
    scraper.export_to_json()