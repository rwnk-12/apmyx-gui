import logging
import multiprocessing
from PyQt6.QtWidgets import QGridLayout, QLabel, QApplication
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QRect, QParallelAnimationGroup, QPoint, QTimer, QEvent, QObject

class LayoutAnimationFeatures:
    

    def eventFilter(self, obj, ev):
      
        if obj is getattr(self, "main_content_container", None) and ev.type() == QEvent.Type.Resize:
          
            if hasattr(self, "_reflow_timer"):
                self._reflow_timer.start(16) 
            else:
                self._reflow_all_grids()
            return False  
        
        return QObject.eventFilter(self, obj, ev)

    def _get_animation_duration(self):
      
        return 137

    def toggle_sidebar(self):
        self.sidebar_open = not self.sidebar_open
        self._animate_panel(self.sidebar, self.sidebar_open, self.sidebar_width)

    def toggle_queue_panel(self):
        self.queue_open = not self.queue_open
        self.queue_toggle_bar.set_open(self.queue_open)
        self._animate_panel(self.queue_panel, self.queue_open, self.queue_panel_width)

    def _animate_panel(self, panel_widget, is_opening, width):
        if self._is_panel_animating:
            return
        self._is_panel_animating = True

        start = panel_widget.width()
        end = int(width) if is_opening else 0

        
        a_min = QPropertyAnimation(panel_widget, b"minimumWidth", self)
        a_min.setStartValue(start)
        a_min.setEndValue(end)
        a_min.setDuration(self._get_animation_duration())
        a_min.setEasingCurve(QEasingCurve.Type.OutCubic)

        a_max = QPropertyAnimation(panel_widget, b"maximumWidth", self)
        a_max.setStartValue(start)
        a_max.setEndValue(end)
        a_max.setDuration(self._get_animation_duration())
        a_max.setEasingCurve(QEasingCurve.Type.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(a_min)
        group.addAnimation(a_max)

        a_min.valueChanged.connect(lambda _:
            self._reflow_timer.start(16) if hasattr(self, "_reflow_timer") else self._reflow_all_grids()
        )

        def on_finish():
           
            panel_widget.setMinimumWidth(end)
            panel_widget.setMaximumWidth(end)
            self._is_panel_animating = False
            
            try:
                if hasattr(self, "queue_panel") and self.queue_panel is panel_widget:
                    self.queue_panel.set_shadow_enabled(not is_opening)
            except Exception:
                pass
            self._reflow_all_grids()

        group.finished.connect(on_finish)
        group.start()
        self.animation = group  

    def _reflow_all_grids(self):
        container_width = self.main_content_container.width()

        for container in self.tab_containers.values():
            
            root_layout = container.layout()
            if isinstance(root_layout, QGridLayout) and root_layout.property("reflowable"):
                self._reflow_grid_layout(root_layout, container_width)

            
            for grid in container.findChildren(QGridLayout):
                if grid is root_layout:
                    continue
                if grid.property("reflowable"):
                    self._reflow_grid_layout(grid, container_width)

    def _reflow_grid_layout(self, layout: QGridLayout, container_width: int):
        mode = (layout.property("mode") or "").lower()
        spacing = layout.horizontalSpacing() or 10

        if mode == "grid_list":
           
            cols = 2 if container_width >= 520 else 1
        else:
            card_width = 190
            cols = max(1, (container_width - spacing) // (card_width + spacing))

        if layout.property("last_cols") == cols:
            return
        layout.setProperty("last_cols", cols)

        container = layout.parentWidget()
        if container:
            container.setUpdatesEnabled(False)
        try:
            widgets = []
            while layout.count():
                item = layout.takeAt(0)
                if item and item.widget():
                    widgets.append(item.widget())
            for i, w in enumerate(widgets):
                layout.addWidget(w, i // cols, i % cols)
            if widgets:
                for r in range(layout.rowCount()):
                    layout.setRowStretch(r, 0)
                layout.setRowStretch(layout.rowCount(), 1)
        finally:
            if container:
                container.setUpdatesEnabled(True)