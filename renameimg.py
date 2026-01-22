import sys
import os
import shutil
import subprocess
from PyQt5.QtWidgets import (QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
                             QGraphicsSimpleTextItem, QGraphicsItem, QFileDialog,
                             QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QLineEdit, QComboBox, QColorDialog, QMessageBox, QFrame,
                             QSlider, QStyle, QListWidget, QCheckBox)
from PyQt5.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont, QColor, QImage, QPainter, QPen, QBrush, QPainterPath, QFontMetrics


# === 1. 自定义点击标签  ===
class SecretLabel(QLabel):
    secret_triggered = pyqtSignal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._click_count = 0
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._reset_count)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._click_count += 1
            self._timer.start()
            if self._click_count >= 5:
                self.secret_triggered.emit()
                self._reset_count()
        super().mousePressEvent(event)

    def _reset_count(self):
        self._click_count = 0


# === 2. 自定义水印文字组件 ===
class DraggableTextItem(QGraphicsSimpleTextItem):
    def __init__(self, text):
        super().__init__(text)
        self.setFlags(
            QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self._fill_color = QColor(255, 255, 255)
        self._outline_color = QColor(0, 0, 0)
        self._outline_width = 4
        # 初始默认字号
        self.setFont(QFont("Arial", 60, QFont.Bold))

    def set_color(self, color):
        self._fill_color = color
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            new_pos = value
            rect = self.boundingRect()
            scene_rect = self.scene().sceneRect()

            # 限制范围逻辑
            if new_pos.x() < scene_rect.left():
                new_pos.setX(scene_rect.left())
            elif new_pos.x() + rect.width() > scene_rect.right():
                new_pos.setX(scene_rect.right() - rect.width())

            if new_pos.y() < scene_rect.top():
                new_pos.setY(scene_rect.top())
            elif new_pos.y() + rect.height() > scene_rect.bottom():
                new_pos.setY(scene_rect.bottom() - rect.height())

            return new_pos

        return super().itemChange(change, value)

    def paint(self, painter, option, widget):
        option.state &= ~QStyle.State_Selected
        path = QPainterPath()
        font = self.font()
        fm = QFontMetrics(font)
        path.addText(0, fm.ascent(), font, self.text())

        pen = QPen(self._outline_color, self._outline_width)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._fill_color))
        painter.drawPath(path)

    def boundingRect(self):
        rect = super().boundingRect()
        margin = self._outline_width / 2
        return rect.adjusted(-margin, -margin, margin, margin)


# === 3. 主程序 ===
class WatermarkApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("拍了个器 - Renameimg")
        self.resize(1200, 850)

        self.image_files = []
        self.current_index = -1
        self.current_image_path = None

        self.scene = QGraphicsScene()
        self.pixmap_item = None
        self.text_item = None
        self.watermark_color = QColor(255, 255, 255)

        # 记录上一张水印，实现延续功能
        self.last_watermark_text = ""

        # 记录位置比例
        self.last_pos_ratio = (0.5, 0.9)

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # === 左侧预览区域 ===
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.view.setStyleSheet("background-color: #e0e0e0; border: 1px solid #ccc;")
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        preview_layout.addWidget(self.view)
        main_layout.addWidget(preview_container, stretch=4)

        # === 悬浮缩放控制条 ===
        self.zoom_overlay = QWidget(self.view)
        self.zoom_overlay.setStyleSheet("""
            QWidget { background-color: rgba(0, 0, 0, 150); border-radius: 15px; }
            QLabel { color: white; background: transparent; font-weight: bold; }
        """)
        self.zoom_overlay.setVisible(False)

        overlay_layout = QHBoxLayout(self.zoom_overlay)
        overlay_layout.setContentsMargins(15, 5, 15, 5)
        overlay_layout.addWidget(QLabel("🔍"))

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(0, 1000)
        self.zoom_slider.setValue(0)
        self.zoom_slider.setFixedWidth(200)
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        overlay_layout.addWidget(self.zoom_slider)

        # === 右侧控制栏 ===
        controls_frame = QFrame()
        controls_frame.setFixedWidth(340)
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setSpacing(8)
        main_layout.addWidget(controls_frame, stretch=1)

        # 1. 打开文件夹
        self.btn_open = QPushButton("📂 打开图片文件夹")
        self.btn_open.setFixedHeight(35)
        self.btn_open.clicked.connect(self.open_folder)
        controls_layout.addWidget(self.btn_open)

        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        controls_layout.addWidget(line1)

        # 2. 水印设置
        controls_layout.addWidget(QLabel("水印内容 (同步文件名):"))
        self.edt_watermark = QLineEdit()
        self.edt_watermark.setPlaceholderText("输入水印...")
        self.edt_watermark.setFixedHeight(30)
        self.edt_watermark.textChanged.connect(self.on_watermark_text_changed)
        controls_layout.addWidget(self.edt_watermark)

        # === 自动适配控件 ===
        hbox_auto = QHBoxLayout()
        # 默认选中“自动置底”，这样每次加载或调整字号都贴底
        self.chk_lock_bottom = QCheckBox("锁定底部")
        self.chk_lock_bottom.setChecked(True)
        self.chk_lock_bottom.setToolTip("选中后，调整字号或加载图片时，水印始终居中贴底")
        self.chk_lock_bottom.stateChanged.connect(self.on_lock_bottom_changed)
        hbox_auto.addWidget(self.chk_lock_bottom)

        self.btn_force_bottom = QPushButton("⬇️ 居中置底")
        self.btn_force_bottom.clicked.connect(self.move_to_bottom_center)
        hbox_auto.addWidget(self.btn_force_bottom)

        controls_layout.addLayout(hbox_auto)

        style_layout = QHBoxLayout()
        vbox_size = QVBoxLayout()
        vbox_size.addWidget(QLabel("文字大小:"))
        self.slider_size = QSlider(Qt.Horizontal)
        self.slider_size.setRange(10, 800)
        self.slider_size.setValue(100)
        self.slider_size.valueChanged.connect(self.update_watermark_style)
        vbox_size.addWidget(self.slider_size)
        style_layout.addLayout(vbox_size)

        self.btn_color = QPushButton("颜色")
        self.btn_color.setFixedSize(50, 40)
        self.btn_color.setStyleSheet(
            f"background-color: {self.watermark_color.name()}; color: black; border: 1px solid gray; border-radius: 4px;")
        self.btn_color.clicked.connect(self.choose_color)
        style_layout.addWidget(self.btn_color)
        controls_layout.addLayout(style_layout)

        hbox_rot = QHBoxLayout()
        hbox_rot.addWidget(QLabel("旋转:"))
        self.combo_rotate = QComboBox()
        self.combo_rotate.addItems(["0", "45", "90", "135", "180", "225", "270", "315"])
        self.combo_rotate.currentIndexChanged.connect(self.update_watermark_style)
        hbox_rot.addWidget(self.combo_rotate)
        controls_layout.addLayout(hbox_rot)

        controls_layout.addWidget(QLabel("输出文件名:"))
        self.edt_filename = QLineEdit()
        self.edt_filename.setFixedHeight(30)
        controls_layout.addWidget(self.edt_filename)

        controls_layout.addSpacing(5)

        self.btn_save = QPushButton("💾 保存并下一张")
        self.btn_save.setFixedHeight(50)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #28a745; color: white; 
                font-size: 15px; font-weight: bold; border-radius: 5px;
            }
            QPushButton:hover { background-color: #218838; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.btn_save.clicked.connect(self.save_and_next)
        controls_layout.addWidget(self.btn_save)

        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("<< 上一张")
        self.btn_prev.setFixedHeight(30)
        self.btn_prev.clicked.connect(self.prev_image)
        self.btn_next = QPushButton("跳过 >>")
        self.btn_next.setFixedHeight(30)
        self.btn_next.clicked.connect(self.next_image)
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.btn_next)
        controls_layout.addLayout(nav_layout)

        controls_layout.addSpacing(10)
        controls_layout.addWidget(QLabel("📂 当前文件列表:"))

        self.file_list_widget = QListWidget()
        self.file_list_widget.itemClicked.connect(self.on_file_list_clicked)
        controls_layout.addWidget(self.file_list_widget)

        # === 底部状态栏区域 ===
        bottom_layout = QHBoxLayout()
        self.lbl_status = SecretLabel("就绪")
        self.lbl_status.setStyleSheet("color: gray; font-size: 11px; padding: 5px;")
        self.lbl_status.secret_triggered.connect(self.show_about_window)
        bottom_layout.addWidget(self.lbl_status)

        self.btn_locate = QPushButton("📂 定位")
        self.btn_locate.setFixedWidth(60)
        self.btn_locate.setStyleSheet("font-size: 11px; padding: 3px;")
        self.btn_locate.clicked.connect(self.locate_in_explorer)
        bottom_layout.addWidget(self.btn_locate)

        controls_layout.addLayout(bottom_layout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'zoom_overlay'):
            w = self.zoom_overlay.width()
            view_width = self.view.width()
            self.zoom_overlay.move(int((view_width - w) / 2), 10)
            self.fit_image_in_view()

    def on_zoom_changed(self, value):
        if not self.pixmap_item:
            return
        scale_factor = 1.0 + (value / 1000.0) * 3.0
        self.view.resetTransform()

        if value == 0:
            self.fit_image_in_view()
            self.view.setDragMode(QGraphicsView.NoDrag)
            if self.text_item:
                self.text_item.setFlag(QGraphicsItem.ItemIsMovable, True)
                self.text_item.setFlag(QGraphicsItem.ItemIsSelectable, True)
            self.btn_save.setEnabled(True)
            self.edt_watermark.setEnabled(True)
        else:
            self.fit_image_in_view(apply_transform=False)
            self.view.scale(scale_factor, scale_factor)
            self.view.setDragMode(QGraphicsView.ScrollHandDrag)
            if self.text_item:
                self.text_item.setFlag(QGraphicsItem.ItemIsMovable, False)
                self.text_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
            self.btn_save.setEnabled(False)
            self.edt_watermark.setEnabled(False)

    def locate_in_explorer(self):
        if not self.current_image_path or not os.path.exists(self.current_image_path):
            QMessageBox.warning(self, "提示", "当前没有文件或文件不存在")
            return
        path = os.path.normpath(self.current_image_path)
        try:
            if sys.platform == 'win32':
                subprocess.Popen(f'explorer /select,"{path}"')
            elif sys.platform == 'darwin':
                subprocess.call(['open', '-R', path])
            else:
                folder = os.path.dirname(path)
                subprocess.Popen(['xdg-open', folder])
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开资源管理器: {str(e)}")

    def on_file_list_clicked(self, item):
        index = self.file_list_widget.row(item)
        if index != self.current_index:
            self.current_index = index
            self.load_image()

    def show_about_window(self):
        title = "关于本软件"
        content = """
        <h3>应用名称：拍了个器-Rename</h3>
        <p><b>版本：</b>Beta 0.3</p>
        <p><b>作者：</b>Xiaojacksonwww</p>
        """
        QMessageBox.about(self, title, content)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if folder:
            valid_exts = ('.jpg', '.jpeg', '.png', '.bmp', '.gif')
            try:
                self.image_files = [os.path.join(folder, f) for f in os.listdir(folder) if
                                    f.lower().endswith(valid_exts)]
                self.image_files.sort()
            except Exception as e:
                QMessageBox.warning(self, "错误", f"读取失败: {e}")
                return

            if not self.image_files:
                QMessageBox.warning(self, "提示", "无图片！")
                return

            self.file_list_widget.clear()
            for f in self.image_files:
                self.file_list_widget.addItem(os.path.basename(f))

            self.current_index = 0
            self.last_watermark_text = ""
            self.load_image()

    def record_current_pos(self):
        if self.zoom_slider.value() != 0:
            return
        # 如果锁定了底部，就不记录手动位置了，以免逻辑冲突
        if self.chk_lock_bottom.isChecked():
            return

        if self.pixmap_item and self.text_item and self.text_item.scene() == self.scene:
            try:
                img_rect = self.pixmap_item.boundingRect()
                w, h = img_rect.width(), img_rect.height()
                if w > 0 and h > 0:
                    pos = self.text_item.pos()
                    self.last_pos_ratio = (pos.x() / w, pos.y() / h)
            except Exception:
                pass

    def load_image(self):
        if not self.image_files:
            return

        if self.current_index < 0 or self.current_index >= len(self.image_files):
            return

        if not os.path.exists(self.image_files[self.current_index]):
            QMessageBox.warning(self, "错误", "文件不存在")
            return

        # 切图时不记录位置，因为我们可能要自动置底
        # self.record_current_pos()

        self.scene.clearSelection()
        self.scene.clear()
        self.pixmap_item = None
        self.text_item = None

        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(0)
        self.zoom_slider.blockSignals(False)
        self.on_zoom_changed(0)

        self.current_image_path = self.image_files[self.current_index]
        file_name = os.path.basename(self.current_image_path)
        base_name = os.path.splitext(file_name)[0]

        self.file_list_widget.setCurrentRow(self.current_index)
        self.file_list_widget.scrollToItem(self.file_list_widget.currentItem())

        self.lbl_status.setText(f"当前文件: {file_name}")
        self.setWindowTitle(f"拍了个器Renameimg - ({self.current_index + 1}/{len(self.image_files)}) {file_name}")

        pixmap = QPixmap(self.current_image_path)
        if pixmap.isNull():
            return

        self.zoom_overlay.setVisible(True)
        self.zoom_overlay.adjustSize()
        w = self.zoom_overlay.width()
        view_width = self.view.width()
        self.zoom_overlay.move(int((view_width - w) / 2), 10)

        self.pixmap_item = self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(QRectF(pixmap.rect()))

        # === 逻辑：延续水印 ===
        initial_watermark = self.last_watermark_text if self.last_watermark_text else ""

        self.edt_watermark.blockSignals(True)
        self.edt_watermark.setText(initial_watermark)
        self.edt_watermark.blockSignals(False)

        self.edt_filename.blockSignals(True)
        if initial_watermark:
            self.edt_filename.setText(initial_watermark)
        else:
            self.edt_filename.setText(base_name)
        self.edt_filename.blockSignals(False)

        self.text_item = DraggableTextItem(initial_watermark)
        self.scene.addItem(self.text_item)

        # 初始位置设置
        if initial_watermark:
            if self.chk_lock_bottom.isChecked():
                self.move_to_bottom_center()
            else:
                img_rect = self.pixmap_item.boundingRect()
                tx = img_rect.width() * self.last_pos_ratio[0]
                ty = img_rect.height() * self.last_pos_ratio[1]
                self.text_item.setPos(tx, ty)
        else:
            self.text_item.setPos(pixmap.width() / 2, pixmap.height() / 2)

        self.update_watermark_style()
        self.fit_image_in_view()

    def fit_image_in_view(self, apply_transform=True):
        if self.pixmap_item and self.zoom_slider.value() == 0 and apply_transform:
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def on_watermark_text_changed(self, text):
        if self.text_item:
            try:
                self.text_item.setText(text)
                self.update_transform_origin()
                # 文本变化时，如果锁定了底部，也重新定位
                if self.chk_lock_bottom.isChecked():
                    self.move_to_bottom_center()
            except RuntimeError:
                self.text_item = None
        self.edt_filename.setText(text)

    def on_lock_bottom_changed(self, state):
        if state == Qt.Checked:
            self.move_to_bottom_center()

    # === 居中置底逻辑 ===
    def move_to_bottom_center(self):
        if not self.text_item or not self.pixmap_item:
            return

        text_content = self.text_item.text()
        if not text_content:
            return

        img_rect = self.pixmap_item.boundingRect()
        img_w = img_rect.width()
        img_h = img_rect.height()

        # 1. 为了计算准确，先归零旋转
        self.combo_rotate.blockSignals(True)
        self.combo_rotate.setCurrentText("0")
        self.text_item.setRotation(0)
        self.combo_rotate.blockSignals(False)

        # 2. 检查宽度，防止文字超宽
        current_size = self.slider_size.value()
        font = self.text_item.font()
        font.setPointSize(current_size)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text_content)

        # 允许的最大宽度 (留点边距)
        max_allowed_width = img_w * 0.96

        # 如果文字比图片还宽，才强制缩小；否则保持设置的大小
        if text_width > max_allowed_width:
            ratio = max_allowed_width / text_width
            new_size = int(current_size * ratio)
            new_size = max(10, new_size)  # 最小保护

            # 更新滑条和字体
            self.slider_size.blockSignals(True)
            self.slider_size.setValue(new_size)
            self.slider_size.blockSignals(False)

            font.setPointSize(new_size)
            self.text_item.setFont(font)
        else:
            # 否则确保使用滑条当前的值
            font.setPointSize(current_size)
            self.text_item.setFont(font)

        # 3. 重新获取精确尺寸
        fm = QFontMetrics(font)
        real_text_width = fm.horizontalAdvance(text_content)
        real_text_height = fm.height()

        # 4. 计算坐标 (居中，紧贴底部)
        x = (img_w - real_text_width) / 2

        # 底部边距：高度的 1% (紧贴)
        margin = img_h * 0.01

        # y 坐标 = 图片高度 - 文字高度 - 边距
        # 注意：QGraphicsSimpleTextItem 的 boundingRect 通常包含了一些上下的 padding
        # 使用 boundingRect().height() 通常比 fm.height() 更能反映在 scene 中的占用
        rect_h = self.text_item.boundingRect().height()
        y = img_h - rect_h - margin

        self.text_item.setPos(x, y)
        self.update_transform_origin()

    def update_watermark_style(self):
        if not self.text_item:
            return
        try:
            self.text_item.set_color(self.watermark_color)
            font = self.text_item.font()
            font.setPointSize(self.slider_size.value())
            self.text_item.setFont(font)

            angle = int(self.combo_rotate.currentText())
            self.text_item.setRotation(angle)
            self.update_transform_origin()

            # 如果锁定了底部，调整大小后自动重新居中置底
            if self.chk_lock_bottom.isChecked():
                self.move_to_bottom_center()

        except RuntimeError:
            self.text_item = None

    def update_transform_origin(self):
        if self.text_item:
            rect = self.text_item.boundingRect()
            self.text_item.setTransformOriginPoint(rect.center())

    def choose_color(self):
        color = QColorDialog.getColor(self.watermark_color, self, "选择颜色")
        if color.isValid():
            self.watermark_color = color
            self.btn_color.setStyleSheet(f"background-color: {color.name()}; color: white; border-radius: 4px;")
            self.update_watermark_style()

    def prev_image(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.load_image()

    def next_image(self):
        if self.current_index < len(self.image_files) - 1:
            self.current_index += 1
            self.load_image()
        else:
            QMessageBox.information(self, "完成", "已经是最后一张了")

    def save_and_next(self):
        if self.zoom_slider.value() > 0:
            QMessageBox.warning(self, "提示", "请先恢复图片缩放(滑条归零)后再保存。")
            return

        if not self.current_image_path or not self.pixmap_item:
            return

        # 记录当前水印内容
        self.last_watermark_text = self.edt_watermark.text()
        self.record_current_pos()

        folder = os.path.dirname(self.current_image_path)
        orig_name = os.path.basename(self.current_image_path)
        orig_stem, ext = os.path.splitext(orig_name)

        # 获取用户输入的基础文件名
        new_stem = self.edt_filename.text().strip()

        if not new_stem:
            QMessageBox.warning(self, "错误", "文件名空")
            return

        # --- 【新增逻辑开始】自动重命名防止覆盖 ---
        # 1. 构造初始目标路径
        save_path = os.path.join(folder, new_stem + ext)

        # 2. 检查文件是否存在
        # 注意：如果目标路径就是当前打开的文件（即没有改名，或者改回了原名），则允许覆盖
        if os.path.exists(save_path) and os.path.abspath(save_path) != os.path.abspath(self.current_image_path):
            counter = 1
            while True:
                # 构造如 name(1).jpg, name(2).jpg 的新文件名
                candidate_name = f"{new_stem}({counter}){ext}"
                candidate_path = os.path.join(folder, candidate_name)

                # 如果这个文件名不存在，就使用它并跳出循环
                if not os.path.exists(candidate_path):
                    save_path = candidate_path
                    break
                counter += 1
        # --- 【新增逻辑结束】 ---

        # 备份
        backup_dir = os.path.join(folder, "backup")
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir)
            except:
                pass
        try:
            # 备份源文件
            shutil.copy2(self.current_image_path, os.path.join(backup_dir, f"{orig_stem}_{new_stem}.bak"))
        except Exception as e:
            print(f"备份警告: {e}")

        self.scene.clearSelection()
        original_size = self.pixmap_item.pixmap().size()
        image = QImage(original_size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.TextAntialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            self.scene.render(painter, target=QRectF(image.rect()), source=self.scene.sceneRect())
        finally:
            painter.end()

        # 保存图片
        if image.save(save_path, None, 100):
            print(f"Saved: {save_path}")

            # 删除原文件逻辑（如果保存路径和原路径不同）
            if os.path.abspath(self.current_image_path) != os.path.abspath(save_path):
                try:
                    os.remove(self.current_image_path)
                    print(f"Deleted original: {self.current_image_path}")
                except Exception as e:
                    print(f"Delete failed: {e}")

            # 更新当前列表中的文件路径和显示名称
            self.image_files[self.current_index] = save_path
            item = self.file_list_widget.item(self.current_index)
            if item:
                item.setText(os.path.basename(save_path))

            self.next_image()
        else:
            QMessageBox.critical(self, "失败", "无法保存")


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    window = WatermarkApp()
    window.show()
    sys.exit(app.exec_())