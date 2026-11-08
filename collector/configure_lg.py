"""User-operated credential/profile form. No network calls and no secret logging."""
import json
from pathlib import Path
import sys
import local_config as config


def main():
    if '--check' in sys.argv:
        import app, chart, hero_link, recommendations, investor_flows
        print('PASS: runtime imports')
        return
    import tkinter as tk
    from tkinter import filedialog, messagebox
    result = {'saved':False}
    window = tk.Tk()
    window.title('LG그램 수집기 · 처음 설정')
    window.resizable(False, False)
    window.option_add('*Font', '{Malgun Gothic} 10')
    box = tk.Frame(window, padx=22, pady=18)
    box.pack()
    tk.Label(box,text='키움 REST API의 App Key / App Secret을 입력하세요.\n계좌 비밀번호를 입력하는 곳이 아닙니다.\n인증정보는 이 Windows 계정으로 암호화해 저장합니다.',justify='left').grid(row=0,column=0,columnspan=2,pady=(0,14))
    tk.Label(box,text='App Key').grid(row=1,column=0,sticky='w')
    key=tk.Entry(box,width=52,show='*');key.grid(row=1,column=1,pady=6)
    tk.Label(box,text='App Secret').grid(row=2,column=0,sticky='w')
    secret=tk.Entry(box,width=52,show='*');secret.grid(row=2,column=1,pady=6)
    folder=tk.StringVar(value=config.settings().get('hero4_profile',''))
    tk.Label(box,text='영웅문 사용자 폴더 (선택 사항)').grid(row=3,column=0,columnspan=2,sticky='w',pady=(14,0))
    tk.Entry(box,textvariable=folder,width=52,state='readonly').grid(row=4,column=1)
    def choose():
        selected=filedialog.askdirectory(parent=window,initialdir=r'C:\KiwoomHero4\user',title='사용 중인 영웅문 사용자 폴더 선택 (Portfolio.dat가 있는 폴더)')
        if selected:folder.set(selected)
    tk.Button(box,text='폴더 선택',command=choose).grid(row=4,column=0,pady=7)
    tk.Label(box,text='폴더를 모르면 비워두세요. 일반 수집은 가능합니다.\n영웅문 메모 파일 직접 쓰기는 초기에는 꺼집니다.\n0311 계좌·메모 경로 확인 후 별도로 활성화해야 합니다.',justify='left').grid(row=5,column=0,columnspan=2,sticky='w',pady=12)
    def save():
        try:
            if folder.get() and not (Path(folder.get())/'Portfolio.dat').is_file():
                raise ValueError('Portfolio.dat가 있는 실제 영웅문 사용자 폴더를 선택하세요.')
            config.save_credentials(key.get(),secret.get())
            settings={'notebook_install':True,'hero4_profile':folder.get(),'memo_write_enabled':False}
            target=config.config_root()/'settings.json';temp=target.with_suffix('.tmp')
            temp.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(target)
            key.delete(0,'end');secret.delete(0,'end');result['saved']=True
            messagebox.showinfo('저장 완료','노트북에 암호화해 저장했습니다.\n키움 허용 IP와 실제 조회 연결은 별도 확인이 필요합니다.',parent=window)
            window.destroy()
        except (OSError,ValueError):
            messagebox.showerror('설정 확인','입력값과 영웅문 폴더를 확인하세요.\n저장 권한 또는 Windows 암호화 오류가 있으면 설치를 중지합니다.',parent=window)
    tk.Button(box,text='저장하고 계속',command=save,width=22).grid(row=6,column=0,columnspan=2,pady=8)
    window.mainloop()
    if not result['saved']:raise SystemExit(2)


if __name__=='__main__':main()
