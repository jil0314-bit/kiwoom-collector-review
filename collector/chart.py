"""Render archived market data to a PNG, independently of browser downloads."""
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from chart_data import PERIODS, COLORS


def render(record, selected=None):
    bars = record['bars']
    frame = record.get('frame', 'minute')
    periods = PERIODS[frame]
    unit = {'day': '일', 'week': '주', 'month': '월', 'minute': '분'}.get(frame, '봉')
    frame_label = {'day': '일봉', 'week': '주봉', 'month': '월봉', 'minute': '1분봉', 'minute3': '3분봉', 'minute5': '5분봉'}[frame]
    image = Image.new('RGB', (1500, 900), 'white')
    draw = ImageDraw.Draw(image)
    font_path = Path('C:/Windows/Fonts/malgun.ttf')
    def font(n):
        return ImageFont.truetype(str(font_path), n) if font_path.exists() else ImageFont.load_default()
    def text(x, y, value, size=17, color='#334155'):
        draw.text((x, y), str(value), font=font(size), fill=color)
    def fmt(n):
        return '—' if n is None else f'{n:,.2f}'.rstrip('0').rstrip('.') if n % 1 else f'{n:,.0f}'
    title = f"{record['stock']['name']} ({record['stock']['code']})  ·  {record['day']}"
    text(35, 22, title, 30, '#172b33')
    text(35, 70, frame_label + ' · KRX+NXT 통합 · 비수정주가 · 데이터 재구성 차트' + (' · 장중 최신' if record['kind']=='preview' else ''))
    for i, n in enumerate(periods):
        text(35+i*140,108,f'{n}{unit}선'+(' (3배 굵기)' if n in (20,60) else ''),16,COLORS[n])
    keys = ['low','high'] + [f'ma{n}' for n in periods]
    values=[b[k] for b in bars for k in keys if b.get(k) is not None]
    lo,hi=min(values),max(values)
    padding=(hi-lo)*.07 or hi*.005
    lo-=padding
    hi+=padding
    left,right,top,bottom=40,1360,155,590
    x=lambda i:left+(i+.5)*(right-left)/(len(bars)+3)
    y=lambda p:top+(hi-p)/(hi-lo)*(bottom-top)
    step=(right-left)/(len(bars)+3)
    for i in range(6):
        p=lo+(hi-lo)*i/5
        yy=y(p)
        draw.line((left,yy,right,yy),fill='#cbd5e1')
        text(right+12,yy-10,fmt(p),15)
    vmax=max(1,max(b['volume'] for b in bars))
    for i,b in enumerate(bars):
        color='#e60012' if b['close']>=b['open'] else '#0057e7'
        xx=x(i)
        half=max(.5,step*.32)
        draw.line((xx,y(b['high']),xx,y(b['low'])),fill=color,width=1)
        lowy,highy=sorted((y(b['open']),y(b['close'])))
        draw.rectangle((xx-half,lowy,xx+half,max(lowy+1,highy)),fill=color)
        draw.rectangle((xx-half,720-b['volume']/vmax*78,xx+half,720),fill=color)
    for n in periods:
        key, color, weight = f'ma{n}', COLORS[n], 6 if n in (20,60) else 2
        points=[]
        for i,b in enumerate(bars):
            if b.get(key) is not None:
                points.append((x(i),y(b[key])))
            else:
                if len(points)>1: draw.line(points,fill=color,width=weight)
                elif points: draw.point(points[0],fill=color)
                points=[]
        if len(points)>1: draw.line(points,fill=color,width=weight)
        elif points: draw.point(points[0],fill=color)
    text(40,610,'거래량 (주)',14)
    for j in range(min(7,len(bars))):
        i=round(j*(len(bars)-1)/max(1,min(7,len(bars))-1))
        ts = bars[i]['ts']
        label = ts[:7] if frame == 'month' else ts if frame in ('day', 'week') else ts[11:16]
        text(x(i)-22,728,label,14)
    b=next((b for b in bars if b['ts']==selected),bars[-1])
    text(35,775,b['ts']+' KST',19,'#172b33')
    text(35,808,'시가 '+fmt(b['open'])+'  |  고가 '+fmt(b['high'])+'  |  저가 '+fmt(b['low'])+'  |  종가 '+fmt(b['close'])+'  |  거래량 '+fmt(b['volume']),19,'#172b33')
    timeline = {'day': '거래일 순서', 'week': '주 시작일 순서', 'month': '월 시작일 순서'}
    text(35,855,timeline.get(frame,'거래 분봉 순서 · 비거래/미제공 시간 구분 미확인')+' · 이력 부족 시 이평선 미표시 · 영웅문 원본 캡처가 아닙니다.',14)
    output=io.BytesIO()
    image.save(output,format='PNG')
    return output.getvalue()
