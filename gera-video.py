#!/usr/bin/env python3
"""
BOM DIA, VAREJO — gerador automático de vídeo vertical (9:16, ~75 s)
                  e de imagens para stories (1080x1920, mesmo visual do vídeo)

Como usar:
  python gera-video.py                  -> cole o JSON no terminal
  python gera-video.py roteiro.json     -> lê o JSON de um arquivo
  python gera-video.py --story          -> força o modo stories (imagens)
  python gera-video.py --testar-vozes   -> gera amostras de todas as vozes pt-BR

Modo servidor (GitHub Actions), sem janelas nem perguntas:
  python gera-video.py roteiro.json --categoria noticia --saida saida

O modo stories é escolhido sozinho quando o JSON tem a lista "stories"
(ou "formato": "story"). Antes de salvar, o script pergunta se o conteúdo é
NOTÍCIA ou CURIOSIDADE e coloca isso no nome do arquivo, para não haver
arquivos com o mesmo nome na pasta.

Música de fundo: coloque arquivos .mp3 numa pasta "musicas" ao lado do script.
  A cada vídeo, uma delas é sorteada.

Instalação (só uma vez):
  pip install edge-tts "moviepy>=2" requests pillow numpy

Banco de imagens (grátis): Pixabay -> https://pixabay.com/api/docs/
  Crie uma conta, copie a chave e cole em PIXABAY_API_KEY abaixo.
  (Pexels também funciona, se você já tiver uma chave.)

Resultado: uma janela do Explorador abre para você escolher onde salvar.
  Vídeo:   [data]_bom-dia-varejo_[noticia|curiosidade].mp4  + _legendas.txt
  Stories: [data]_story_[noticia|curiosidade].jpg  (uma imagem por JSON)
           Coloque um logo.png ao lado do script para usar seu logo na barra branca.
"""

import asyncio
import json
import os
import re
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

import edge_tts
import numpy as np
import requests
from moviepy import (AudioFileClip, ColorClip, CompositeAudioClip,
                     CompositeVideoClip, ImageClip, VideoFileClip,
                     afx, concatenate_videoclips, vfx)
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ============================ CONFIGURAÇÃO ============================
def _chave_local(nome_arquivo):
    """Lê a chave de um .txt ao lado do script (só no seu PC; nunca suba para o GitHub)."""
    arq = Path(__file__).resolve().parent / nome_arquivo
    return arq.read_text(encoding="utf-8").strip() if arq.exists() else ""


# No GitHub, as chaves vêm dos Secrets. No PC, de chave_pixabay.txt / chave_pexels.txt.
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY") or _chave_local("chave_pixabay.txt")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY") or _chave_local("chave_pexels.txt")
VOZ_PADRAO = "pt-BR-ThalitaMultilingualNeural"   # rode --testar-vozes e troque aqui
VELOCIDADE = "+8%"                   # aumente/diminua para ajustar a duração
TOM = "-2Hz"                         # grave/agudo: ex. "-4Hz" (mais sério), "+0Hz"
PASTA_INICIAL = Path.home() / "Videos"   # pasta sugerida na janela de salvar
PASTA_MUSICAS = Path(__file__).resolve().parent / "musicas"
VOLUME_MUSICA = 0.07                 # 0.06 = bem baixo | 0.15 = mais presente
APAGAR_TEMPORARIOS = True

W, H, FPS = 1080, 1920, 30
# Paleta: preto, branco e laranja
COR_DESTAQUE = (0, 0, 0)             # caixa de destaque: preta
COR_TEXTO_DESTAQUE = (255, 255, 255) # texto do destaque: branco
COR_TEXTO_MARCA = (255, 255, 255)    # nome do canal: branco
COR_MARCA = (0, 0, 0)                # selo do canal e fundo liso: preto
TAMANHO_LEGENDA = 54                 # legenda falada (antes era 74)
NOME_CANAL = "BOM DIA, VAREJO"
# Posições verticais (px) — afastadas da ilha/câmera e da barra do topo dos apps
Y_MARCA = 250        # selo "BOM DIA, VAREJO"
Y_FONTE = 365        # linha "Fonte: ..."
Y_DESTAQUE = int(1920 * 0.33)  # caixa de destaque da cena
DURACAO_MINIMA = 61                  # TikTok só monetiza vídeos com mais de 1 min
MIN_PALAVRAS_CENA = 8                # cenas menores são juntadas à seguinte
TRANSICAO = 0.3                      # segundos de fusão suave entre as cenas
# Stories (imagem estática)
PASTA_INICIAL_STORIES = Path.home() / "Pictures"
# Visual do story (estilo manchete de portal): barra branca + fundo preto
STORY_TOPO_LIVRE = 230               # faixa preta no topo: indicadores e perfil do Instagram
STORY_ALT_BARRA = 170                # altura da barra branca
STORY_BASE_LIVRE = 300               # faixa livre embaixo: campo de resposta
STORY_MARGEM = 72                    # margem lateral do texto
STORY_TITULO = 104                   # tamanho máximo do título (diminui sozinho se faltar espaço)
STORY_TEXTO = 46                     # tamanho do texto de apoio
COR_STORY_FUNDO = (0, 0, 0)
COR_STORY_BARRA = (255, 255, 255)
COR_STORY_TITULO = (255, 255, 255)
COR_STORY_TEXTO = (175, 175, 175)
LOGO_ARQUIVO = Path(__file__).resolve().parent / "logo.png"   # opcional
QUALIDADE_JPG = 95
# ======================================================================

FONTES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",   # servidor Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
ABERTOS = []  # clipes que usam o FFmpeg; são fechados no final
SESSAO = requests.Session()
SESSAO.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BomDiaVarejo/1.0"})
SESSAO.mount("https://", requests.adapters.HTTPAdapter(max_retries=requests.adapters.Retry(
    total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"])))


# ------------------------------ ENTRADA -------------------------------
OPCOES_COM_VALOR = ("--categoria", "--saida")


def opcao(nome):
    """Valor de uma opção da linha de comando, ex.: --saida pasta."""
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def posicionais():
    resto, pular = [], False
    for a in sys.argv[1:]:
        if pular:
            pular = False
        elif a in OPCOES_COM_VALOR:
            pular = True
        elif not a.startswith("--"):
            resto.append(a)
    return resto


SEM_JANELA = opcao("--saida") is not None   # modo servidor


def ler_roteiro():
    arquivos = posicionais()
    if arquivos:
        texto = Path(arquivos[0]).read_text(encoding="utf-8-sig")
        texto = re.sub(r"^\s*```(?:json)?\s*$", "", texto, flags=re.M).strip()
        return json.loads(texto)

    print("Cole o JSON do roteiro e pressione Enter "
          "(o script continua sozinho quando o JSON estiver completo):\n")
    linhas = []
    while True:
        try:
            linhas.append(input())
        except EOFError:
            break
        texto = "\n".join(linhas)
        texto = re.sub(r"^\s*```(?:json)?\s*$", "", texto, flags=re.M).strip()
        if texto.startswith("{"):
            try:
                return json.loads(texto)
            except json.JSONDecodeError:
                continue
    raise SystemExit("Não foi possível ler o JSON. Confira se ele foi copiado inteiro.")


def juntar_cenas_curtas(cenas):
    """Junta cenas com pouca fala à cena seguinte, para não aparecer uma imagem
    piscando por menos de um segundo."""
    resultado, pendente = [], None
    for cena in cenas:
        if pendente:
            cena = {**cena,
                    "narracao": f"{pendente['narracao']} {cena['narracao']}",
                    "texto_tela": cena.get("texto_tela") or pendente.get("texto_tela", ""),
                    "fonte": cena.get("fonte") or pendente.get("fonte")}
            pendente = None
        curta = len(cena["narracao"].split()) < MIN_PALAVRAS_CENA
        if curta and not eh_cena_fixa(cena) and cena is not cenas[-1]:
            pendente = cena
            continue
        resultado.append(cena)
    if pendente:  # sobrou uma cena curta no fim: junta à anterior
        if resultado and not eh_cena_fixa(resultado[-1]):
            ant = resultado[-1]
            ant["narracao"] = f"{ant['narracao']} {pendente['narracao']}"
        else:
            resultado.append(pendente)
    juntadas = len(cenas) - len(resultado)
    if juntadas:
        print(f"{juntadas} cena(s) curta(s) juntada(s) à seguinte.")
    return resultado


def validar(roteiro):
    if not roteiro.get("cenas"):
        raise SystemExit("O JSON não tem a lista 'cenas'.")
    for i, c in enumerate(roteiro["cenas"], 1):
        if not c.get("narracao"):
            raise SystemExit(f"A cena {i} está sem 'narracao'.")
    roteiro.setdefault("data", "sem-data")
    roteiro["voz"] = VOZ_PADRAO  # a voz é sempre a da configuração do script


def conferir_voz(voz):
    """Confere se a voz existe no serviço; se não, mostra as opções e usa a padrão."""
    async def listar():
        return {v["ShortName"]: v.get("Locale", "") for v in await edge_tts.list_voices()}
    try:
        vozes = asyncio.run(listar())
    except Exception as e:
        print(f"Aviso: não consegui listar as vozes ({e}). Tentando usar {voz} assim mesmo.")
        return voz
    if voz in vozes:
        print(f"Voz: {voz}")
        return voz
    pt = sorted(n for n, loc in vozes.items() if loc == "pt-BR")
    multi = sorted(n for n in vozes if "Multilingual" in n)
    print(f"\nA voz '{voz}' não existe no serviço usado pelo script.")
    print("Vozes pt-BR disponíveis: " + ", ".join(pt))
    if multi:
        print("Vozes multilíngues (falam português com sotaque estrangeiro): " + ", ".join(multi))
    reserva = "pt-BR-AntonioNeural" if "pt-BR-AntonioNeural" in vozes else (pt[0] if pt else voz)
    print(f"Usando {reserva} neste vídeo.\n")
    return reserva


# ------------------------------- TEXTO --------------------------------
FONTES_SERIFA = [
    "C:/Windows/Fonts/georgiab.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Georgia_Bold.ttf",  # servidor Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]


FONTES_REGULAR = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

# Só os títulos (título do story e caixa de destaque do vídeo):
# News Gothic MT Bold (vem com o Office).
# No GitHub ela não existe; usa a News Cycle Bold, versão gratuita inspirada nela.
FAMILIAS_TITULO = [("News Gothic MT", "Bold"), ("News Cycle", "Bold")]
PASTAS_DE_FONTES = [Path(__file__).resolve().parent / "fontes",
                    Path("C:/Windows/Fonts"), Path.home() / ".fonts",
                    Path.home() / ".local/share/fonts", Path.home() / "Library/Fonts",
                    Path("/Library/Fonts"), Path("/usr/share/fonts")]
if os.getenv("LOCALAPPDATA"):
    PASTAS_DE_FONTES.insert(2, Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts")
_FONTES_ACHADAS = {}


def achar_fonte_por_nome(familia, estilo):
    """Procura uma fonte instalada pelo nome (ex.: 'News Gothic MT', 'Bold')."""
    chave = (familia.lower(), estilo.lower())
    if chave not in _FONTES_ACHADAS:
        achada = None
        for pasta in PASTAS_DE_FONTES:
            if achada or not pasta.is_dir():
                continue
            for arq in pasta.rglob("*"):
                if arq.suffix.lower() not in (".ttf", ".otf"):
                    continue
                try:
                    nome, tipo = ImageFont.truetype(str(arq), 10).getname()
                except Exception:
                    continue
                if (nome or "").lower() == chave[0] and (tipo or "").lower() == chave[1]:
                    achada = str(arq)
                    break
        _FONTES_ACHADAS[chave] = achada
    return _FONTES_ACHADAS[chave]


def fonte_regular(tamanho):
    for caminho in FONTES_REGULAR:
        if os.path.exists(caminho):
            return ImageFont.truetype(caminho, tamanho)
    return fonte(tamanho)


def fonte_titulo(tamanho):
    for familia, estilo in FAMILIAS_TITULO:
        caminho = achar_fonte_por_nome(familia, estilo)
        if caminho:
            return ImageFont.truetype(caminho, tamanho)
    return fonte(tamanho)


def fonte(tamanho, serifa=False):
    for caminho in (FONTES_SERIFA if serifa else []) + FONTES:
        if os.path.exists(caminho):
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default(size=tamanho)


def quebrar_linhas(texto, font, largura_max, draw):
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = f"{atual} {palavra}".strip()
        if draw.textlength(teste, font=font) <= largura_max or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def imagem_texto(texto, tamanho, cor=(255, 255, 255), fundo=None, serifa=False, titulo=False,
                 largura_max=W - 160, contorno=6, margem=28):
    font = fonte_titulo(tamanho) if titulo else fonte(tamanho, serifa)
    rascunho = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    linhas = quebrar_linhas(texto, font, largura_max - 2 * margem, rascunho)
    ascendente, descendente = font.getmetrics()
    alt_linha = ascendente + descendente
    espaco = int(tamanho * 0.12)
    largura = max(rascunho.textlength(l, font=font) for l in linhas)
    iw = int(largura + 2 * (margem + contorno))
    ih = int(len(linhas) * alt_linha + (len(linhas) - 1) * espaco + 2 * (margem + contorno))

    img = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if fundo:
        d.rounded_rectangle([0, 0, iw - 1, ih - 1], radius=24, fill=fundo)
    y = margem + contorno
    for linha in linhas:
        x = (iw - d.textlength(linha, font=font)) / 2
        d.text((x, y), linha, font=font, fill=cor,
               stroke_width=0 if fundo else contorno, stroke_fill=(0, 0, 0))
        y += alt_linha + espaco
    return img


def clip_imagem(img, duracao, posicao, inicio=0.0):
    return (ImageClip(np.array(img), transparent=True)
            .with_duration(duracao).with_start(inicio).with_position(posicao))


# ------------------------------ NARRAÇÃO ------------------------------
async def _narrar(texto, voz, caminho):
    try:
        com = edge_tts.Communicate(texto, voz, rate=VELOCIDADE, pitch=TOM,
                                   boundary="WordBoundary")
    except TypeError:  # versões antigas do edge-tts
        com = edge_tts.Communicate(texto, voz, rate=VELOCIDADE, pitch=TOM)
    palavras = []
    with open(caminho, "wb") as f:
        async for parte in com.stream():
            if parte["type"] == "audio":
                f.write(parte["data"])
            elif parte["type"] == "WordBoundary":
                ini = parte["offset"] / 1e7
                palavras.append((ini, ini + parte["duration"] / 1e7, parte["text"]))
    return palavras


def narrar(texto, voz, caminho):
    return asyncio.run(_narrar(texto, voz, caminho))


def blocos_legenda(palavras, texto, duracao, max_palavras=3):
    if not palavras:  # sem marcação de tempo: distribui pelo tamanho das palavras
        lista = texto.split()
        total = sum(len(p) + 1 for p in lista)
        t = 0.0
        for p in lista:
            d = duracao * (len(p) + 1) / total
            palavras.append((t, t + d, p))
            t += d

    blocos = [palavras[i:i + max_palavras] for i in range(0, len(palavras), max_palavras)]
    resultado = []
    for i, bloco in enumerate(blocos):
        ini = bloco[0][0]
        fim = blocos[i + 1][0][0] if i + 1 < len(blocos) else duracao
        resultado.append((ini, max(fim, ini + 0.2), " ".join(p[2] for p in bloco)))
    return resultado


# ------------------------------- PEXELS -------------------------------
def baixar(url, destino, tentativas=4):
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    parcial = destino.with_suffix(destino.suffix + ".part")
    for n in range(1, tentativas + 1):
        try:
            with SESSAO.get(url, stream=True, timeout=(15, 60)) as r:
                r.raise_for_status()
                with open(parcial, "wb") as f:
                    for pedaco in r.iter_content(256 * 1024):
                        f.write(pedaco)
            parcial.replace(destino)
            return destino
        except Exception as e:
            parcial.unlink(missing_ok=True)
            if n == tentativas:
                raise
            print(f"   conexão caiu, tentando de novo ({n}/{tentativas - 1})...")
            time.sleep(2 * n)


def pegar_json(url, params, cab=None):
    r = SESSAO.get(url, params=params, headers=cab, timeout=(15, 30))
    r.raise_for_status()
    return r.json()


# Palavras que indicam imagem fora do tema (descartadas sempre)
PROIBIDAS = {
    "dance", "dancing", "dancer", "party", "club", "disco", "concert", "music",
    "fashion", "model", "sexy", "bikini", "beach", "wedding", "love", "couple",
    "kiss", "halloween", "christmas", "santa", "horror", "ghost", "zombie",
    "fantasy", "anime", "cartoon", "game", "gaming", "fitness", "yoga", "gym",
    "sport", "football", "soccer", "night", "dark", "nightlife", "neon", "fireworks",
    "house", "home", "bedroom", "religion", "church", "war", "weapon", "gun",
    "blood", "smoke", "drink", "alcohol", "beer", "wine", "selfie", "portrait",
    "girl", "boy", "baby", "kids", "children",
    # imagens com texto, montagens e ilustrações (baixa qualidade no vídeo)
    "greeting", "greetings", "text", "lettering", "typography", "quote", "quotes",
    "words", "message", "font", "illustration", "vector", "drawing", "clipart",
    "clip-art", "animation", "animated", "3d", "render", "wallpaper", "emoji",
    "logo", "banner", "poster", "frame", "heart", "hearts", "valentine",
}
# Palavras do universo do varejo/economia (dão pontos extras)
TEMA = {
    "supermarket", "grocery", "store", "shop", "shopping", "retail", "market",
    "shelf", "shelves", "aisle", "cart", "trolley", "basket", "cashier",
    "checkout", "warehouse", "wholesale", "logistics", "truck", "delivery",
    "boxes", "box", "pallet", "food", "fruit", "vegetables", "coffee", "rice",
    "beans", "meat", "milk", "bread", "price", "money", "coins", "cash",
    "finance", "economy", "business", "chart", "graph", "stock", "bank",
    "calculator", "receipt", "payment", "card", "agriculture", "farm",
    "harvest", "factory", "industry", "port", "container", "fuel", "office",
}
GENERICAS = ["supermarket aisle", "grocery store shelves", "shopping cart",
             "warehouse boxes", "money coins"]

# Abertura ("Bom dia, varejo!") e fechamento: imagens sorteadas a cada vídeo
BUSCAS_ABERTURA = ["sunrise", "morning sky", "sunrise city", "morning sun",
                   "sunrise clouds", "sunrise landscape"]
BUSCAS_FECHAMENTO = ["drinking coffee", "morning coffee", "coffee cup",
                     "coffee mug", "sunrise", "sunrise sky"]
# termos que deixam de ser proibidos nessas cenas (pessoa tomando café etc.)
LIBERAR_FIXAS = frozenset({"drink", "girl", "portrait", "home", "house"})


def _raiz(palavra):
    """Normaliza plural simples: stripes -> stripe, boxes -> box."""
    w = palavra.strip().lower()
    if len(w) > 4 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _palavras_tags(tags_texto):
    tags = [t.strip().lower() for t in tags_texto.split(",") if t.strip()]
    palavras = {_raiz(w) for t in tags for w in t.split()}
    palavras |= {_raiz(t.replace(" ", "")) for t in tags}  # "bar code" -> "barcode"
    return palavras


def pontuar(tags_texto, busca, liberar=frozenset()):
    """Nota de relevância de uma imagem para o termo de busca.
    As tags do Pixabay vêm em ordem de importância e as últimas costumam ser
    ruído ("fish, carp, ..., gum"). Por isso o termo inteiro precisa estar
    nas PRIMEIRAS tags:
      termo nas 1ª tag -> 10 | nas 2 primeiras -> 7 | nas 3 primeiras -> 4
      fora das 3 primeiras -> 0 (descartada) | termo proibido -> -1"""
    tags = [t.strip().lower() for t in tags_texto.split(",") if t.strip()]
    todas = _palavras_tags(tags_texto)
    if todas & {_raiz(p) for p in (PROIBIDAS - liberar)}:
        return -1
    termos = {_raiz(w) for w in busca.split()}
    for k, nota in ((1, 10), (2, 7), (3, 4)):
        if termos <= _palavras_tags(",".join(tags[:k])):
            return nota + min(2, len(todas & {_raiz(t) for t in TEMA}))
    return 0


# --------------------- CONTROLE DE REPETIÇÃO -------------------------
# Só vale durante a execução atual: nada é gravado em disco.
# "usados" guarda, para este vídeo:
#   - o id de cada imagem já escolhida;
#   - o autor de cada imagem (o mesmo autor costuma subir várias tomadas
#     quase iguais com ids diferentes);
#   - a "assinatura" das tags (vídeos com tags idênticas são quase sempre
#     a mesma filmagem).
def assinatura(tags_texto):
    return "tags:" + ",".join(sorted(t.strip() for t in tags_texto.lower().split(",") if t.strip()))


def ja_usado(usados, chave, autor=None, tags=None):
    if chave in usados:
        return True
    if autor and f"autor:{autor}" in usados:
        return True
    if tags and assinatura(tags) in usados:
        return True
    return False


def marcar(usados, chave, autor=None, tags=None):
    usados.add(chave)
    if autor:
        usados.add(f"autor:{autor}")
    if tags:
        usados.add(assinatura(tags))


def variar(candidatos, folga=2):
    """Embaralha só os candidatos de nota próxima à melhor: mantém o foco no
    tema e faz cada execução escolher imagens diferentes, sem guardar histórico."""
    if not candidatos:
        return []
    melhor = max(n for n, _ in candidatos)
    bons = [c for c in candidatos if c[0] >= melhor - folga]
    resto = sorted((c for c in candidatos if c[0] < melhor - folga), key=lambda x: -x[0])
    random.shuffle(bons)
    return bons + resto


def tem_chave(chave):
    return bool(chave) and "COLE_SUA" not in chave


_CACHE_API = {}


def _pixabay(url, params):
    chave = (url, tuple(sorted(params.items())))
    if chave not in _CACHE_API:
        _CACHE_API[chave] = pegar_json(url, params).get("hits", [])
    return _CACHE_API[chave]


def buscar_pixabay(busca, usados, pasta, liberar=frozenset(), sortear=False, fotos_ok=False,
                   estrito=False, so_fotos=False):
    """Busca vídeos E fotos do termo e escolhe o mais fiel ao tema.
    Vídeo só ganha da foto quando a relevância é igual."""
    if fotos_ok:  # a foto já é avaliada junto com o vídeo, na mesma chamada
        return None
    base = {"key": PIXABAY_API_KEY, "q": busca, "safesearch": "true",
            "per_page": 50, "order": "popular"}
    minimo = 4

    candidatos = []
    videos = [] if so_fotos else _pixabay("https://pixabay.com/api/videos/",
                                          {**base, "video_type": "film"})
    for h in videos:
        chave, tags = f"pixabay_v{h['id']}", h.get("tags", "")
        if ja_usado(usados, chave, h.get("user_id"), tags):
            continue
        nota = pontuar(tags, busca, liberar)
        if nota < minimo:
            continue
        arquivos = [a for a in h["videos"].values()
                    if a.get("url") and min(a.get("width", 0), a.get("height", 0)) >= 720]
        if not arquivos:
            continue
        escolhido = min(arquivos, key=lambda a: abs(max(a["width"], a["height"]) - 1280))
        vertical = escolhido["height"] >= escolhido["width"]
        candidatos.append((nota + 0.5 + (0.5 if vertical else 0),
                           ("video", escolhido["url"], chave, h)))

    for h in _pixabay("https://pixabay.com/api/", {**base, "image_type": "photo",
                                                    "orientation": "vertical"}):
        chave, tags = f"pixabay_f{h['id']}", h.get("tags", "")
        if ja_usado(usados, chave, h.get("user_id"), tags):
            continue
        nota = pontuar(tags, busca, liberar)
        if nota < minimo or h.get("imageHeight", 0) < 1600:  # evita fotos pequenas
            continue
        candidatos.append((nota, ("foto", h["largeImageURL"], chave, h)))

    for _, (tipo, url, chave, h) in variar(candidatos, folga=2 if sortear else 1):
        ext = "mp4" if tipo == "video" else "jpg"
        try:
            midia = tipo, baixar(url, pasta / f"{chave}.{ext}")
            marcar(usados, chave, h.get("user_id"), h.get("tags", ""))
            return midia
        except Exception as e:
            usados.add(chave)
            print(f"   {tipo} {h['id']} não baixou ({type(e).__name__}); tentando outro...")
    return None


def buscar_pexels(busca, usados, pasta, liberar=frozenset(), sortear=False, fotos_ok=False,
                  estrito=False, so_fotos=False):
    if fotos_ok:
        return None
    cab = {"Authorization": PEXELS_API_KEY}
    if so_fotos:
        dados = pegar_json("https://api.pexels.com/v1/search",
                           {"query": busca, "orientation": "portrait", "per_page": 30}, cab)
        fotos = [f for f in dados.get("photos", [])
                 if not ja_usado(usados, f"pexels_f{f['id']}", f.get("photographer_id"))
                 and f.get("height", 0) >= 1600]
        random.shuffle(fotos)
        for f in fotos:
            chave = f"pexels_f{f['id']}"
            try:
                midia = "foto", baixar(f["src"]["large2x"], pasta / f"{chave}.jpg")
                marcar(usados, chave, f.get("photographer_id"))
                return midia
            except Exception as e:
                usados.add(chave)
                print(f"   foto {f['id']} não baixou ({type(e).__name__}); tentando outra...")
        return None
    dados = pegar_json("https://api.pexels.com/videos/search",
                       {"query": busca, "orientation": "portrait", "per_page": 30}, cab)
    videos = [v for v in dados.get("videos", [])
              if not ja_usado(usados, f"pexels_v{v['id']}", (v.get("user") or {}).get("id"))]
    random.shuffle(videos)
    for v in videos:
        arquivos = [a for a in v.get("video_files", [])
                    if a.get("width") and a.get("height")
                    and a["height"] >= a["width"] and a["height"] >= 1280]
        if not arquivos:
            continue
        escolhido = min(arquivos, key=lambda a: abs(a["height"] - 1920))
        chave = f"pexels_v{v['id']}"
        try:
            midia = "video", baixar(escolhido["link"], pasta / f"{chave}.mp4")
            marcar(usados, chave, (v.get("user") or {}).get("id"))
            return midia
        except Exception as e:
            usados.add(chave)
            print(f"   vídeo {v['id']} não baixou ({type(e).__name__}); tentando outro...")
    return None


def buscar_midia(buscas, usados, pasta, liberar=frozenset(), sortear=False, genericas=True,
                 reforco=None, so_fotos=False):
    """reforco: termos extras do mesmo tema (usados no gancho), tentados antes
    das imagens genéricas e com filtro estrito."""
    if isinstance(buscas, str):
        buscas = [buscas]
    especificas = [b for b in (buscas or []) if b]
    gerais = GENERICAS if genericas else []
    fontes = []
    if tem_chave(PIXABAY_API_KEY):
        fontes.append(("Pixabay", buscar_pixabay))
    if tem_chave(PEXELS_API_KEY):
        fontes.append(("Pexels", buscar_pexels))

    # Ordem: cada termo da cena (vídeo, depois foto), do mais específico ao
    # mais genérico; no gancho, depois os termos da notícia; por último,
    # as imagens genéricas de varejo.
    tema = list(especificas)
    if reforco:
        tema += [b for b in reforco if b and b not in tema]
    if so_fotos:  # stories: uma rodada por termo, só fotos
        rodadas = [([t], False, True) for t in tema] + [(gerais, False, True)]
    else:
        rodadas = [([t], fotos, True) for t in tema for fotos in (False, True)]
        rodadas += [(gerais, False, True), (gerais, True, True)]
    for termos, fotos_ok, estrito in rodadas:
        for busca in termos:
            for nome, funcao in fontes:
                try:
                    midia = funcao(busca, usados, pasta, liberar, sortear, fotos_ok, estrito,
                                   so_fotos=so_fotos)
                    if midia:
                        print(f"   imagem: '{busca}' ({nome}, {midia[0]})")
                        return midia
                except Exception as e:
                    print(f"   aviso: {nome} falhou para '{busca}': {e}")
    return None


# ------------------------------- CENAS --------------------------------
def cobrir_tela(clip):
    escala = max(W / clip.w, H / clip.h) * 1.002
    clip = clip.resized(escala)
    return clip.cropped(x1=int((clip.w - W) / 2), y1=int((clip.h - H) / 2), width=W, height=H)


def montar_fundo(midia, duracao):
    if midia and midia[0] == "video":
        try:
            original = VideoFileClip(str(midia[1]), audio=False)
            ABERTOS.append(original)
            c = cobrir_tela(original)
            if c.duration >= duracao:
                return c.subclipped(0, duracao)
            return c.with_effects([vfx.Loop(duration=duracao)])
        except Exception as e:
            print(f"   aviso: vídeo ignorado ({e})")
    if midia and midia[0] == "foto":
        try:
            img = cobrir_tela(ImageClip(str(midia[1])).with_duration(duracao))
            zoom = img.resized(lambda t: 1 + 0.06 * t / duracao)  # zoom lento
            return CompositeVideoClip([zoom.with_position("center")], size=(W, H)).with_duration(duracao)
        except Exception as e:
            print(f"   aviso: foto ignorada ({e})")
    return ColorClip((W, H), color=COR_MARCA).with_duration(duracao)


def eh_cena_fixa(cena):
    if cena.get("tipo") in ("abertura", "fechamento"):
        return True
    t = cena["narracao"].lower()
    return t.startswith("bom dia, varejo") or t.startswith("isso foi o bom dia")


def termos_da_noticia(roteiro, a_partir_de):
    """Termos de busca das cenas de notícia seguintes, para reforçar o gancho."""
    termos = []
    for c in roteiro["cenas"][a_partir_de:]:
        if eh_cena_fixa(c):
            continue
        b = c.get("busca_imagem") or []
        termos += [b] if isinstance(b, str) else list(b)[:1]
        if len(termos) >= 4:
            break
    return termos


def montar_cena(i, cena, roteiro, pasta, usados, img_marca):
    print(f"-> Cena {i}: {cena['narracao'][:60]}...")
    caminho_audio = pasta / f"cena_{i:02d}.mp3"
    palavras = narrar(cena["narracao"], roteiro["voz"], caminho_audio)
    audio = AudioFileClip(str(caminho_audio))
    ABERTOS.append(audio)
    duracao = audio.duration + TRANSICAO + 0.1  # silêncio no fim cobre a fusão

    tipo = cena.get("tipo")
    if eh_cena_fixa(cena):
        fechamento = tipo == "fechamento" or cena["narracao"].lower().startswith("isso foi")
        buscas = list(BUSCAS_FECHAMENTO if fechamento else BUSCAS_ABERTURA)
        random.shuffle(buscas)
        midia = buscar_midia(buscas, usados, pasta, LIBERAR_FIXAS, sortear=True, genericas=False)
        cena = {**cena, "texto_tela": ""}
    else:
        primeira = not any(not eh_cena_fixa(c) for c in roteiro["cenas"][:i - 1])
        if tipo == "gancho" or primeira:
            midia = buscar_midia(cena.get("busca_imagem"), usados, pasta,
                                 reforco=termos_da_noticia(roteiro, i))
        else:
            midia = buscar_midia(cena.get("busca_imagem"), usados, pasta)

    camadas = [
        montar_fundo(midia, duracao),
        ColorClip((W, H), color=(0, 0, 0)).with_opacity(0.38).with_duration(duracao),
        clip_imagem(img_marca, duracao, ("center", Y_MARCA)),
    ]

    fonte_txt = cena.get("fonte") or roteiro.get("fonte")
    if fonte_txt:
        img_fonte = imagem_texto(fonte_txt, 34, cor=(230, 230, 230), contorno=3, margem=10)
        camadas.append(clip_imagem(img_fonte, duracao, ("center", Y_FONTE)))

    if cena.get("texto_tela"):
        img_destaque = imagem_texto(cena["texto_tela"].upper(), 92, cor=COR_TEXTO_DESTAQUE, titulo=True,
                                    fundo=COR_DESTAQUE + (240,), largura_max=W - 140)
        camadas.append(clip_imagem(img_destaque, duracao, ("center", Y_DESTAQUE)))

    for ini, fim, texto in blocos_legenda(palavras, cena["narracao"], audio.duration):
        img_legenda = imagem_texto(texto, TAMANHO_LEGENDA, serifa=True, contorno=4)
        camadas.append(clip_imagem(img_legenda, fim - ini, ("center", int(H * 0.64)), ini))

    return CompositeVideoClip(camadas, size=(W, H)).with_duration(duracao).with_audio(audio)


# ------------------------------- SAÍDA --------------------------------
def salvar_legendas(roteiro, caminho):
    partes = [f"TÍTULO: {roteiro.get('titulo', '')}", ""]
    for rede, texto in (roteiro.get("legendas") or {}).items():
        partes += [f"=== {rede.upper()} ===", texto, ""]
    caminho.write_text("\n".join(partes), encoding="utf-8")


CATEGORIAS = {"1": "noticia", "2": "curiosidade"}
APELIDOS = {"noticia": "noticia", "notícia": "noticia", "noticias": "noticia",
            "notícias": "noticia", "n": "noticia", "curiosidade": "curiosidade",
            "curiosidades": "curiosidade", "c": "curiosidade"}


def escolher_categoria(sugestao=None):
    """Pergunta no terminal se o conteúdo é notícia ou curiosidade."""
    padrao = APELIDOS.get(str(sugestao or "").strip().lower())
    forcada = APELIDOS.get(str(opcao("--categoria") or "").strip().lower())
    if forcada:
        return forcada
    if SEM_JANELA:
        return padrao or "noticia"
    dica = f" (Enter = {padrao})" if padrao else ""
    while True:
        try:
            r = input(f"\nTipo do conteúdo — [1] Notícia  [2] Curiosidade{dica}: ").strip().lower()
        except EOFError:
            r = ""
        if not r and padrao:
            return padrao
        escolha = CATEGORIAS.get(r) or APELIDOS.get(r)
        if escolha:
            return escolha
        print("Digite 1 para Notícia ou 2 para Curiosidade.")


def caminho_livre(caminho):
    """Se o arquivo já existe, acrescenta _2, _3... ao nome."""
    caminho = Path(caminho)
    n = 2
    novo = caminho
    while novo.exists():
        novo = caminho.with_name(f"{caminho.stem}_{n}{caminho.suffix}")
        n += 1
    return novo


def escolher_destino(nome, titulo="Salvar vídeo do Bom dia, Varejo", ext=".mp4",
                     tipos=(("Vídeo MP4", "*.mp4"),), pasta=None):
    if SEM_JANELA:  # servidor: salva direto na pasta indicada, sem sobrescrever
        destino = Path(opcao("--saida"))
        destino.mkdir(parents=True, exist_ok=True)
        return caminho_livre(destino / nome)
    import tkinter as tk
    from tkinter import filedialog
    pasta = pasta or PASTA_INICIAL
    inicial = pasta if pasta.exists() else Path.home()
    sugerido = caminho_livre(inicial / nome).name
    raiz = tk.Tk()
    raiz.withdraw()
    raiz.attributes("-topmost", True)
    caminho = filedialog.asksaveasfilename(
        parent=raiz, title=titulo, initialdir=str(inicial), initialfile=sugerido,
        defaultextension=ext, filetypes=list(tipos))
    raiz.destroy()
    if not caminho:
        raise SystemExit("Salvamento cancelado. Nenhum arquivo foi gerado.")
    return Path(caminho)


# ------------------------------ STORIES -------------------------------
def validar_stories(roteiro):
    stories = roteiro.get("stories")
    if not stories:  # aceita também um story único no próprio JSON
        if roteiro.get("texto_tela") or roteiro.get("texto_apoio") or roteiro.get("topicos"):
            stories = [roteiro]
        else:
            raise SystemExit("O JSON não tem a lista 'stories'.")
    for i, s in enumerate(stories, 1):
        if not (s.get("texto_tela") or s.get("texto_apoio") or s.get("topicos")):
            raise SystemExit(f"O story {i} está sem 'texto_tela', 'texto_apoio' e 'topicos'.")
    roteiro["stories"] = stories
    roteiro.setdefault("data", "sem-data")


def _logo(tamanho):
    """Logo redondo: usa logo.png (recortado em círculo) se existir; senão um selo "BV"."""
    escala = 4  # desenha maior e reduz, para a borda do círculo ficar lisa
    grande = tamanho * escala
    mascara = Image.new("L", (grande, grande), 0)
    ImageDraw.Draw(mascara).ellipse([0, 0, grande - 1, grande - 1], fill=255)
    if LOGO_ARQUIVO.exists():
        try:
            img = ImageOps.fit(Image.open(LOGO_ARQUIVO).convert("RGBA"), (grande, grande),
                               Image.LANCZOS)
            alfa = Image.composite(img.getchannel("A"), Image.new("L", img.size, 0), mascara)
            img.putalpha(alfa)
            return img.resize((tamanho, tamanho), Image.LANCZOS)
        except Exception as e:
            print(f"   aviso: logo.png ignorado ({e})")
    img = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, grande - 1, grande - 1], fill=COR_STORY_FUNDO)
    d.text((grande / 2, grande / 2), "BV", font=fonte(int(grande * 0.40)),
           fill=COR_STORY_BARRA, anchor="mm")
    return img.resize((tamanho, tamanho), Image.LANCZOS)


def _data_br(data):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(data or ""))
    return f"{m[3]}/{m[2]}/{m[1]}" if m else str(data or "")


def montar_story(item, roteiro):
    titulo = (item.get("texto_tela") or "").strip()
    apoio = (item.get("texto_apoio") or "").strip()
    topicos = [str(x).strip() for x in (item.get("topicos") or []) if str(x).strip()]
    print(f"-> Story: {(titulo or apoio or ' '.join(topicos))[:60]}...")

    tela = Image.new("RGB", (W, H), COR_STORY_FUNDO)
    d = ImageDraw.Draw(tela)

    # Barra branca abaixo da área dos indicadores do stories
    y0, y1 = STORY_TOPO_LIVRE, STORY_TOPO_LIVRE + STORY_ALT_BARRA
    d.rectangle([0, y0, W, y1], fill=COR_STORY_BARRA)
    logo = _logo(int(STORY_ALT_BARRA * 0.62))
    tela.paste(logo, (STORY_MARGEM - 12, y0 + (STORY_ALT_BARRA - logo.height) // 2), logo)
    d.text((W / 2, (y0 + y1) / 2), NOME_CANAL, font=fonte_regular(62),
           fill=COR_STORY_FUNDO, anchor="mm")

    # Texto da notícia, alinhado à esquerda como manchete de portal
    largura = W - 2 * STORY_MARGEM
    topo = y1 + 110
    limite = H - STORY_BASE_LIVRE
    rodape_txt = item.get("fonte") or roteiro.get("fonte") or f"Por {NOME_CANAL.title()}"
    data_txt = _data_br(item.get("data") or roteiro.get("data"))

    recuo = 46  # espaço entre a bolinha e o texto do tópico

    def bloco(tam_titulo, tam_texto):
        # cada linha: (texto, fonte, cor, x, altura_da_linha, bolinha?)
        linhas, altura = [], 0

        def add(lista, f, cor, alt, depois, x=STORY_MARGEM, bolinha=False):
            nonlocal altura
            for n, txt in enumerate(lista):
                linhas.append((txt, f, cor, x, altura, bolinha and n == 0))
                altura += alt
            altura += depois

        if titulo:
            ft = fonte_titulo(tam_titulo)
            add(quebrar_linhas(titulo, ft, largura, d), ft, COR_STORY_TITULO,
                int(tam_titulo * 1.12), int(tam_texto * 1.2))
        if apoio:
            fa = fonte_regular(tam_texto)
            add(quebrar_linhas(apoio, fa, largura, d), fa, COR_STORY_TEXTO,
                int(tam_texto * 1.38), int(tam_texto * 0.8))
        if topicos:
            fa = fonte_regular(tam_texto)
            for tp in topicos:
                add(quebrar_linhas(tp, fa, largura - recuo, d), fa, COR_STORY_TEXTO,
                    int(tam_texto * 1.32), int(tam_texto * 0.55),
                    x=STORY_MARGEM + recuo, bolinha=True)
        altura += int(tam_texto * 0.6)
        add([rodape_txt], fonte(int(tam_texto * 0.86)), COR_STORY_TEXTO,
            int(tam_texto * 1.25), 6)
        if data_txt:
            add([data_txt], fonte_regular(int(tam_texto * 0.78)), COR_STORY_TEXTO,
                int(tam_texto * 1.1), 0)
        return linhas, altura

    tam_t, tam_a = STORY_TITULO, STORY_TEXTO
    linhas, altura = bloco(tam_t, tam_a)
    while topo + altura > limite and tam_t > 60:  # texto longo: diminui até caber
        tam_t, tam_a = tam_t - 4, max(34, tam_a - 1)
        linhas, altura = bloco(tam_t, tam_a)

    for txt, f, cor, x, y, bolinha in linhas:
        if bolinha:
            r = max(6, int(f.size * 0.16))
            cy = topo + y + f.size * 0.58
            d.ellipse([STORY_MARGEM + 4, cy - r, STORY_MARGEM + 4 + 2 * r, cy + r],
                      fill=COR_STORY_TITULO)
        d.text((x, topo + y), txt, font=f, fill=cor)
    return tela


def gerar_stories(roteiro):
    validar_stories(roteiro)
    stories = roteiro["stories"]
    if len(stories) > 1:
        print(f"Aviso: o JSON tem {len(stories)} stories; só o primeiro é gerado.")
    categoria = escolher_categoria(roteiro.get("categoria"))
    saida = escolher_destino(f"{roteiro['data']}_story_{categoria}.jpg",
                             titulo="Salvar story do Bom dia, Varejo", ext=".jpg",
                             tipos=(("Imagem JPG", "*.jpg"), ("Imagem PNG", "*.png")),
                             pasta=PASTA_INICIAL_STORIES)
    img = montar_story(stories[0], roteiro)
    if saida.suffix.lower() == ".png":
        img.save(saida)
    else:
        img.save(saida, "JPEG", quality=QUALIDADE_JPG, optimize=True)
    print(f"\nPronto! {saida}")


def testar_vozes():
    async def listar():
        return [v["ShortName"] for v in await edge_tts.list_voices()
                if v["Locale"] == "pt-BR"]
    vozes = asyncio.run(listar())
    print("Vozes pt-BR encontradas: " + ", ".join(vozes))
    pasta = Path(__file__).resolve().parent / "amostras_vozes"
    pasta.mkdir(exist_ok=True)
    frase = ("Bom dia, varejo! A inflação dos alimentos desacelerou em setembro, "
             "e isso pode aliviar o preço da cesta básica nas próximas semanas.")
    for voz in vozes:
        print(f"Gerando {voz}...")
        try:
            narrar(frase, voz, pasta / f"{voz}.mp3")
        except Exception as e:
            print(f"   falhou: {e}")
    print(f"\nAmostras salvas em: {pasta}")
    if os.name == "nt":
        os.startfile(pasta)


def main():
    if "--testar-vozes" in sys.argv:
        testar_vozes()
        return
    roteiro = ler_roteiro()
    if ("--story" in sys.argv or roteiro.get("formato") == "story"
            or "stories" in roteiro):
        gerar_stories(roteiro)
        return
    validar(roteiro)
    roteiro["cenas"] = juntar_cenas_curtas(roteiro["cenas"])

    roteiro["voz"] = conferir_voz(roteiro["voz"])
    data = roteiro["data"]
    categoria = escolher_categoria(roteiro.get("categoria"))
    saida = escolher_destino(f"{data}_bom-dia-varejo_{categoria}.mp4")
    pasta_tmp = Path(tempfile.mkdtemp(prefix="bom_dia_varejo_"))

    if not (tem_chave(PIXABAY_API_KEY) or tem_chave(PEXELS_API_KEY)):
        print("Aviso: sem chave do Pixabay, as cenas terão fundo liso.\n")

    img_marca = imagem_texto(NOME_CANAL, 44, cor=COR_TEXTO_MARCA,
                             fundo=COR_MARCA + (230,), margem=18)
    usados = set()
    cenas = [montar_cena(i, c, roteiro, pasta_tmp, usados, img_marca)
             for i, c in enumerate(roteiro["cenas"], 1)]

    # fusão suave: cada cena começa um pouco antes do fim da anterior
    inicio, partes = 0.0, []
    for i, c in enumerate(cenas):
        if i > 0:
            c = c.with_effects([vfx.CrossFadeIn(TRANSICAO)])
        partes.append(c.with_start(inicio))
        inicio += c.duration - TRANSICAO
    video = CompositeVideoClip(partes, size=(W, H)).with_duration(inicio + TRANSICAO)
    musicas = sorted(p for p in PASTA_MUSICAS.glob("*")
                     if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")) \
        if PASTA_MUSICAS.exists() else []
    if musicas:
        escolhida = random.choice(musicas)
        print(f"Música de fundo: {escolhida.name}")
        musica = AudioFileClip(str(escolhida))
        ABERTOS.append(musica)
        trilha = musica.with_effects([
            afx.AudioLoop(duration=video.duration),
            afx.MultiplyVolume(VOLUME_MUSICA),
            afx.AudioFadeIn(1.0),
            afx.AudioFadeOut(2.5),
        ])
        video = video.with_audio(CompositeAudioClip([video.audio, trilha]))
    else:
        print("Sem música de fundo (pasta 'musicas' vazia ou inexistente).")

    video.write_videofile(str(saida), fps=FPS, codec="libx264", audio_codec="aac",
                          preset="medium", threads=4,
                          temp_audiofile=str(pasta_tmp / "audio_temp.m4a"))
    salvar_legendas(roteiro, saida.with_name(f"{saida.stem}_legendas.txt"))

    for clip in [video, *cenas, *ABERTOS]:
        try:
            clip.close()
        except Exception:
            pass
    if APAGAR_TEMPORARIOS:
        shutil.rmtree(pasta_tmp, ignore_errors=True)

    print(f"\nPronto! {saida}  ({video.duration:.0f} s)")
    if video.duration < DURACAO_MINIMA:
        print(f"Atenção: o vídeo tem menos de {DURACAO_MINIMA} s e não monetiza no TikTok. "
              "Diminua VELOCIDADE (ex.: '+0%') ou peça um roteiro um pouco maior.")


if __name__ == "__main__":
    main()