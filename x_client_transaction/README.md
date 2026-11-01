# `x_client_transaction` — X (Twitter) `X-Client-Transaction-Id` Üretici

X.com (eski adıyla Twitter) dahili REST (`/1.1/...`, `/2/...`) ve GraphQL (`/i/api/graphql/...`, `/graphql/...`) uç noktalarının zorunlu tuttuğu dinamik **`x-client-transaction-id`** başlığını üreten bağımsız Python modülü.

Bu sürüm, X.com'un hem eski hem de yeni web istemci mimarilerini destekleyecek şekilde güncellenmiştir:

- **Klasik `responsive-web` Mimarisi:** Webpack tabanlı `ondemand.s.*.js` paket çözümlemesi.
- **Yeni `x-web` (ESM / Rolldown) Mimarisi:** `entry-client-*.js` → `startup-dynamic-*.js` → `sign.o-*.js` otomatik zincir çözümlemesi.
- **Çoklu Rota Yedekleme & Yönlendirme Koruması:** `/i/jf/`, `/x/migrate` ve `/` rotaları arasında otomatik geçiş ve `TooManyRedirects` döngü koruması.
- **Otomatik `path` Normalizasyonu:** Tam URL, `?query=...` veya `#fragment` içeren yolları X istemcisinin imzalama kuralına uygun şekilde yalnızca `pathname` kalacak biçimde temizler (`jf.x.com` özel durumu dahil).

---

## Kurulum ve Başka Projeye Taşıma

Harici bir paket kurulumuna gerek yoktur; `x_client_transaction` klasörünü doğrudan projenizin kök dizinine kopyalamanız yeterlidir.

Gerekli kütüphaneler:

```bash
pip install beautifulsoup4 curl_cffi
```

> `curl_cffi` yerine standart `requests` veya `httpx` oturumlarıyla da çalışır; ancak X.com TLS parmak izi kontrolü nedeniyle `curl_cffi` (`impersonate="chrome"` / `"chrome136"`) önerilir.

---

## Hızlı Kullanım

### 1. Senkron Kullanım (`curl_cffi` veya `requests`)

Başlangıçta ana sayfa ve imza betiği **bir kez** çekilip `ClientTransaction` başlatılır; sonrasında aynı nesne üzerinden sınırsız sayıda işlem kimliği (her istek için taze zaman damgalı ve rastgele XOR anahtarlı) üretilir.

```python
from curl_cffi import requests
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import (
    generate_headers,
    get_ondemand_file_url,
    handle_x_migration,
)

# 1. Oturum oluştur ve X ana sayfasını çek
session = requests.Session(impersonate="chrome136")
session.headers.update(generate_headers())

home_page = handle_x_migration(session)
script_url = get_ondemand_file_url(response=home_page, session=session)
if not script_url:
    raise RuntimeError("İmza betiği URL'si çözümlenemedi")

script_text = session.get(script_url, timeout=20).text

# 2. Üreticiyi başlat (bellekte tut ve tekrar kullan)
ct = ClientTransaction(
    home_page_response=home_page,
    ondemand_file_response=script_text,
)

# 3. Her API isteği öncesinde ilgili method ve path için yeni ID üret
txid_post = ct.generate_transaction_id(
    method="POST",
    path="/1.1/account/update_profile_image.json",
)

txid_graphql = ct.generate_transaction_id(
    method="GET",
    path="/i/api/graphql/-oaLodhGbbnzJBACb1kk2Q/UserByScreenName",
)
```

---

### 2. Asenkron Kullanım (`AsyncSession` veya `httpx.AsyncClient`)

```python
import asyncio
from curl_cffi.requests import AsyncSession
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import (
    generate_headers,
    get_ondemand_file_url,
    handle_x_migration_async,
)


async def main():
    async with AsyncSession(impersonate="chrome") as session:
        session.headers.update(generate_headers())

        home_page = await handle_x_migration_async(session)
        script_url = get_ondemand_file_url(response=home_page)
        if not script_url:
            raise RuntimeError("İmza betiği URL'si çözümlenemedi")

        resp = await session.get(script_url, timeout=20)
        ct = ClientTransaction(
            home_page_response=home_page,
            ondemand_file_response=resp.text,
        )

        txid = ct.generate_transaction_id(
            method="POST",
            path="/1.1/onboarding/task.json",
        )
        print("x-client-transaction-id:", txid)


asyncio.run(main())
```

---

### 3. Çoklu Thread / Yüksek Eşzamanlılık Şablonu (Önerilen)

50+ iş parçacığı veya asenkron görev çalıştıran araçlarda her hesap için X ana sayfasını tekrar indirmeyin. Aşağıdaki thread-safe sarmalayıcı ana sayfayı yalnızca ilk çağrıda indirir, tüm işçilere sıfır ağ gecikmesiyle ID üretir ve hata halinde kendini sıfırlar:

```python
import threading
from typing import Optional
from curl_cffi.requests import Session
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import (
    generate_headers,
    get_ondemand_file_url,
    handle_x_migration,
)


class TransactionIdProvider:
    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout
        self._lock = threading.RLock()
        self._client: Optional[ClientTransaction] = None

    def generate(self, method: str, path: str) -> str:
        last_err: Optional[Exception] = None
        for _ in range(2):
            try:
                client = self._ensure_client()
                return client.generate_transaction_id(method=method, path=path)
            except Exception as exc:
                last_err = exc
                self.reset()
        raise RuntimeError(f"Transaction ID üretilemedi: {last_err}")

    def _ensure_client(self) -> ClientTransaction:
        with self._lock:
            if self._client is not None:
                return self._client
            with Session(impersonate="chrome136") as session:
                session.headers.update(generate_headers())
                home_page = handle_x_migration(session)
                script_url = get_ondemand_file_url(response=home_page, session=session)
                if not script_url:
                    raise RuntimeError("ondemand.s / sign.o URL'si bulunamadı")
                script_text = session.get(script_url, timeout=self._timeout).text
                self._client = ClientTransaction(
                    home_page_response=home_page,
                    ondemand_file_response=script_text,
                )
                return self._client

    def reset(self) -> None:
        with self._lock:
            self._client = None
```

---

## Önemli İmzalama Kuralları (`method` ve `path`)

X.com sunucusu gönderilen `x-client-transaction-id` başlığını doğrularken **isteğin gönderildiği gerçek URL'nin `pathname` bölümünü** ve **büyük harfli HTTP metodunu** kontrol eder:

| İstek Gönderilen Tam Adres | `method` | Verilmesi Gereken `path` |
| :--- | :---: | :--- |
| `https://api.x.com/1.1/account/verify_password.json` | `"POST"` | `"/1.1/account/verify_password.json"` |
| `https://api.x.com/1.1/onboarding/task.json?flow_name=add_email` | `"POST"` | `"/1.1/onboarding/task.json"` |
| `https://x.com/i/api/graphql/<id>/UserByScreenName?variables=...` | `"GET"` | `"/i/api/graphql/<id>/UserByScreenName"` |
| `https://api.x.com/graphql/<id>/UserByScreenName?variables=...` | `"GET"` | `"/graphql/<id>/UserByScreenName"` |

- **Host farkına dikkat edin:** İsteği `https://x.com/i/api/graphql/...` adresine atıyorsanız `path` başında `/i/api` **olmalıdır**; isteği `https://api.x.com/graphql/...` adresine atıyorsanız `path` başında `/i/api` **olmamalıdır**. Kısaca istek attığınız tam URL'yi doğrudan `path` parametresine de verebilirsiniz (`ct.generate_transaction_id("GET", full_url)`); modül doğru `pathname` değerini otomatik ayıklar.
- **Query parametreleri imzaya girmez:** `?variables=...` veya `?flow_name=...` yanlışlıkla `path` içinde gönderilse bile `generate_transaction_id` bunları otomatik temizler.
- **Uzun süreli çalışan süreçler:** 7/24 çalışan botlarda X'in yeni istemci sürümü dağıtma ihtimaline karşı birkaç saatte bir `ClientTransaction` örneğini yenilemek iyi bir pratiktir.

---

## Modül Dosya Yapısı

| Dosya | Görevi |
| :--- | :--- |
| `__init__.py` | `ClientTransaction` sınıfını dışa aktarır. |
| `transaction.py` | Anahtar baytları, SVG animasyon matrisi, SHA-256 ve XOR tabanlı `generate_transaction_id` çekirdeği. |
| `utils.py` | Ana sayfa çekimi (`handle_x_migration`), yönlendirme koruması, `ondemand.s` ve `x-web` (`sign.o`) URL çözümleyicisi. |
| `constants.py` | Sabitler ve hem Webpack hem Rolldown paketleri için kullanılan düzenli ifadeler (regex). |
| `cubic_curve.py` | CSS `cubic-bezier` eğri çözücüsü. |
| `interpolate.py` | Renk ve açı doğrusal enterpolasyon yardımcıları. |
| `rotation.py` | Derece → 2B CSS dönüşüm matrisi hesaplayıcısı. |

