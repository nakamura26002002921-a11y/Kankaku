# latentsense/view.py
from psychopy import visual, core, event

class PsychoPyView:
    def __init__(self, size=(1024, 768), fullscr=False):
        self.win = visual.Window(size=size, color='white', units='pix', fullscr=fullscr)
        self.mouse = event.Mouse(win=self.win)
        self.clock = core.Clock()  # 反応時間計測用
        
        # ⚠️ 環境に合わせて日本語フォントを指定してください
        # Windows: 'Meiryo', Mac: 'Hiragino Sans', Linux: 'Noto Sans CJK JP'
        self.default_font = 'Meiryo' 

    def close(self):
        self.win.close()

    def _draw_text(self, text, pos=(0, 0), height=30, color='black', align='center'):
        """内部ヘルパー: テキスト刺激を描画キューに追加"""
        stim = visual.TextStim(
            self.win, text=text, pos=pos, height=height, 
            color=color, alignText=align, wrapWidth=900,
            font=self.default_font  # 日本語フォントを適用
        )
        stim.draw()

    def show_loading(self, message="処理中..."):
        """ローディング画面の表示"""
        self.win.color = 'white'
        self._draw_text(message, height=40, color='gray')
        self.win.flip()

    def show_scenario(self, concept_name, situation, option_a, option_b):
        """シナリオと選択肢の表示"""
        self.win.color = 'white'
        self._draw_text(f"🎯 Target: {concept_name}", pos=(0, 300), height=35, color='darkblue')
        self._draw_text(f"📖 Situation:\n{situation}", pos=(0, 150), height=30, color='black')
        
        # 選択肢は少し見やすく枠や記号をつける
        self._draw_text(f"[ A ]\n{option_a}", pos=(-250, -100), height=28, color='black')
        self._draw_text(f"[ B ]\n{option_b}", pos=(250, -100), height=28, color='black')
        
        self._draw_text("A または B のキーを押して回答してください", pos=(0, -300), height=24, color='gray')
        self.win.flip()

    def show_feedback(self, is_correct, correct_answer, user_choice, analysis, metaphor):
        """フィードバック画面の表示"""
        # PsychoPyで色名を使う場合、少し暗めの背景の方が見やすい場合があります
        self.win.color = 'palegreen' if is_correct else 'lightpink'
        result_text = "🟢 CORRECT: Prediction Matched" if is_correct else "🔴 PREDICTION ERROR: Neural Rewiring Required"
        
        self._draw_text(result_text, pos=(0, 250), height=35, color='black')
        self._draw_text(f"正解: {correct_answer} (あなたの選択: {user_choice})", pos=(0, 150), height=28)
        self._draw_text(f"🔍 Diagnosis:\n{analysis}", pos=(0, 0), height=26, color='black')
        self._draw_text(f"🔮 Expert Metaphor:\n{metaphor}", pos=(0, -150), height=26, color='darkblue')
        self._draw_text("スペースキーを押して次へ (Escで終了)", pos=(0, -320), height=24, color='gray')
        self.win.flip()

    # --- 入力待機メソッド ---
    def wait_for_choice(self):
        """A または B の選択を待つ。キーと反応時間をタプルで返す"""
        self.clock.reset() # ⚠️ ここでタイマーをリセット
        keys = event.waitKeys(keyList=['a', 'b', 'escape'], timeStamped=self.clock)
        if not keys: return 'ESCAPE', 0
        
        key_name, reaction_time = keys[0]
        if key_name == 'escape': return 'ESCAPE', 0
        return key_name.upper(), int(reaction_time * 1000) # (選択, RT[ms])を返す

    def wait_for_confidence(self):
        """1~5 の自信度入力待つ。"""
        keys = event.waitKeys(keyList=['1', '2', '3', '4', '5', 'escape'])
        if not keys or 'escape' in keys: return 'ESCAPE'
        return int(keys[0])

    def wait_for_continue(self):
        """次へ進むのを待つ。"""
        keys = event.waitKeys(keyList=['space', 'escape'])
        return 'ESCAPE' if not keys or 'escape' in keys else 'CONTINUE'
