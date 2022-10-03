import sys
import re
import traceback
import copy

import qtawesome
try:
    import commonmark
except Exception:
    commonmark = None
from Qt import QtWidgets, QtCore, QtGui

from openpype.client import get_asset_by_name, get_subsets
from openpype.pipeline.create import (
    CreatorError,
    SUBSET_NAME_ALLOWED_SYMBOLS,
    TaskNotSetError,
)
from openpype.tools.utils import (
    ErrorMessageBox,
    MessageOverlayObject,
    ClickableFrame,
)

from .widgets import (
    IconValuePixmapLabel,
    CreateBtn,
)
from .assets_widget import CreateWidgetAssetsWidget
from .tasks_widget import CreateWidgetTasksWidget
from .precreate_widget import PreCreateWidget
from ..constants import (
    VARIANT_TOOLTIP,
    CREATOR_IDENTIFIER_ROLE,
    FAMILY_ROLE
)

SEPARATORS = ("---separator---", "---")


class VariantInputsWidget(QtWidgets.QWidget):
    resized = QtCore.Signal()

    def resizeEvent(self, event):
        super(VariantInputsWidget, self).resizeEvent(event)
        self.resized.emit()


class CreateErrorMessageBox(ErrorMessageBox):
    def __init__(
        self,
        creator_label,
        subset_name,
        asset_name,
        exc_msg,
        formatted_traceback,
        parent
    ):
        self._creator_label = creator_label
        self._subset_name = subset_name
        self._asset_name = asset_name
        self._exc_msg = exc_msg
        self._formatted_traceback = formatted_traceback
        super(CreateErrorMessageBox, self).__init__("Creation failed", parent)

    def _create_top_widget(self, parent_widget):
        label_widget = QtWidgets.QLabel(parent_widget)
        label_widget.setText(
            "<span style='font-size:18pt;'>Failed to create</span>"
        )
        return label_widget

    def _get_report_data(self):
        report_message = (
            "{creator}: Failed to create Subset: \"{subset}\""
            " in Asset: \"{asset}\""
            "\n\nError: {message}"
        ).format(
            creator=self._creator_label,
            subset=self._subset_name,
            asset=self._asset_name,
            message=self._exc_msg,
        )
        if self._formatted_traceback:
            report_message += "\n\n{}".format(self._formatted_traceback)
        return [report_message]

    def _create_content(self, content_layout):
        item_name_template = (
            "<span style='font-weight:bold;'>Creator:</span> {}<br>"
            "<span style='font-weight:bold;'>Subset:</span> {}<br>"
            "<span style='font-weight:bold;'>Asset:</span> {}<br>"
        )
        exc_msg_template = "<span style='font-weight:bold'>{}</span>"

        line = self._create_line()
        content_layout.addWidget(line)

        item_name_widget = QtWidgets.QLabel(self)
        item_name_widget.setText(
            item_name_template.format(
                self._creator_label, self._subset_name, self._asset_name
            )
        )
        content_layout.addWidget(item_name_widget)

        message_label_widget = QtWidgets.QLabel(self)
        message_label_widget.setText(
            exc_msg_template.format(self.convert_text_for_html(self._exc_msg))
        )
        content_layout.addWidget(message_label_widget)

        if self._formatted_traceback:
            line_widget = self._create_line()
            tb_widget = self._create_traceback_widget(
                self._formatted_traceback
            )
            content_layout.addWidget(line_widget)
            content_layout.addWidget(tb_widget)


# TODO add creator identifier/label to details
class CreatorShortDescWidget(QtWidgets.QWidget):
    height_changed = QtCore.Signal(int)

    def __init__(self, parent=None):
        super(CreatorShortDescWidget, self).__init__(parent=parent)

        # --- Short description widget ---
        icon_widget = IconValuePixmapLabel(None, self)
        icon_widget.setObjectName("FamilyIconLabel")

        # --- Short description inputs ---
        short_desc_input_widget = QtWidgets.QWidget(self)

        family_label = QtWidgets.QLabel(short_desc_input_widget)
        family_label.setAlignment(
            QtCore.Qt.AlignBottom | QtCore.Qt.AlignLeft
        )

        description_label = QtWidgets.QLabel(short_desc_input_widget)
        description_label.setAlignment(
            QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft
        )

        short_desc_input_layout = QtWidgets.QVBoxLayout(
            short_desc_input_widget
        )
        short_desc_input_layout.setSpacing(0)
        short_desc_input_layout.addWidget(family_label)
        short_desc_input_layout.addWidget(description_label)
        # --------------------------------

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(icon_widget, 0)
        layout.addWidget(short_desc_input_widget, 1)
        # --------------------------------

        self._icon_widget = icon_widget
        self._family_label = family_label
        self._description_label = description_label

        self._last_height = None

    def _check_height_change(self):
        height = self.height()
        if height != self._last_height:
            self._last_height = height
            self.height_changed.emit(height)

    def showEvent(self, event):
        super(CreatorShortDescWidget, self).showEvent(event)
        self._check_height_change()

    def resizeEvent(self, event):
        super(CreatorShortDescWidget, self).resizeEvent(event)
        self._check_height_change()

    def set_plugin(self, plugin=None):
        if not plugin:
            self._icon_widget.set_icon_def(None)
            self._family_label.setText("")
            self._description_label.setText("")
            return

        plugin_icon = plugin.get_icon()
        description = plugin.get_description() or ""

        self._icon_widget.set_icon_def(plugin_icon)
        self._family_label.setText("<b>{}</b>".format(plugin.family))
        self._family_label.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        self._description_label.setText(description)


class HelpButton(ClickableFrame):
    resized = QtCore.Signal(int)
    question_mark_icon_name = "fa.question"
    help_icon_name = "fa.question-circle"
    hide_icon_name = "fa.angle-left"

    def __init__(self, *args, **kwargs):
        super(HelpButton, self).__init__(*args, **kwargs)
        self.setObjectName("CreateDialogHelpButton")

        question_mark_label = QtWidgets.QLabel(self)
        help_widget = QtWidgets.QWidget(self)

        help_question = QtWidgets.QLabel(help_widget)
        help_label = QtWidgets.QLabel("Help", help_widget)
        hide_icon = QtWidgets.QLabel(help_widget)

        help_layout = QtWidgets.QHBoxLayout(help_widget)
        help_layout.setContentsMargins(0, 0, 5, 0)
        help_layout.addWidget(help_question, 0)
        help_layout.addWidget(help_label, 0)
        help_layout.addStretch(1)
        help_layout.addWidget(hide_icon, 0)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(question_mark_label, 0)
        layout.addWidget(help_widget, 1)

        help_widget.setVisible(False)

        self._question_mark_label = question_mark_label
        self._help_widget = help_widget
        self._help_question = help_question
        self._hide_icon = hide_icon

        self._expanded = None
        self.set_expanded()

    def set_expanded(self, expanded=None):
        if self._expanded is expanded:
            if expanded is not None:
                return
            expanded = False
        self._expanded = expanded
        self._help_widget.setVisible(expanded)
        self._update_content()

    def _update_content(self):
        width = self.get_icon_width()
        if self._expanded:
            question_mark_pix = QtGui.QPixmap(width, width)
            question_mark_pix.fill(QtCore.Qt.transparent)

        else:
            question_mark_icon = qtawesome.icon(
                self.question_mark_icon_name, color=QtCore.Qt.white
            )
            question_mark_pix = question_mark_icon.pixmap(width, width)

        hide_icon = qtawesome.icon(
            self.hide_icon_name, color=QtCore.Qt.white
        )
        help_question_icon = qtawesome.icon(
            self.help_icon_name, color=QtCore.Qt.white
        )
        self._question_mark_label.setPixmap(question_mark_pix)
        self._question_mark_label.setMaximumWidth(width)
        self._hide_icon.setPixmap(hide_icon.pixmap(width, width))
        self._help_question.setPixmap(help_question_icon.pixmap(width, width))

    def get_icon_width(self):
        metrics = self.fontMetrics()
        return metrics.height()

    def set_pos_and_size(self, pos_x, pos_y, width, height):
        update_icon = self.height() != height
        self.move(pos_x, pos_y)
        self.resize(width, height)

        if update_icon:
            self._update_content()
            self.updateGeometry()

    def showEvent(self, event):
        super(HelpButton, self).showEvent(event)
        self.resized.emit(self.height())

    def resizeEvent(self, event):
        super(HelpButton, self).resizeEvent(event)
        self.resized.emit(self.height())


class CreateWidget(QtWidgets.QWidget):
    def __init__(self, controller, parent=None):
        super(CreateWidget, self).__init__(parent)

        self.setWindowTitle("Create new instance")

        self._controller = controller

        self._asset_name = self.dbcon.Session.get("AVALON_ASSET")
        self._task_name = self.dbcon.Session.get("AVALON_TASK")

        self._asset_doc = None
        self._subset_names = None
        self._selected_creator = None

        self._prereq_available = False

        self._message_dialog = None

        name_pattern = "^[{}]*$".format(SUBSET_NAME_ALLOWED_SYMBOLS)
        self._name_pattern = name_pattern
        self._compiled_name_pattern = re.compile(name_pattern)

        main_splitter_widget = QtWidgets.QSplitter(self)

        context_widget = QtWidgets.QWidget(main_splitter_widget)

        assets_widget = CreateWidgetAssetsWidget(controller, context_widget)
        tasks_widget = CreateWidgetTasksWidget(controller, context_widget)

        context_layout = QtWidgets.QVBoxLayout(context_widget)
        context_layout.setContentsMargins(0, 0, 0, 0)
        context_layout.setSpacing(0)
        context_layout.addWidget(assets_widget, 2)
        context_layout.addWidget(tasks_widget, 1)

        # --- Creators view ---
        creators_widget = QtWidgets.QWidget(main_splitter_widget)

        creator_short_desc_widget = CreatorShortDescWidget(creators_widget)

        attr_separator_widget = QtWidgets.QWidget(creators_widget)
        attr_separator_widget.setObjectName("Separator")
        attr_separator_widget.setMinimumHeight(1)
        attr_separator_widget.setMaximumHeight(1)

        creators_splitter = QtWidgets.QSplitter(creators_widget)

        creators_view_widget = QtWidgets.QWidget(creators_splitter)

        creator_view_label = QtWidgets.QLabel(
            "Choose publish type", creators_view_widget
        )

        creators_view = QtWidgets.QListView(creators_view_widget)
        creators_model = QtGui.QStandardItemModel()
        creators_sort_model = QtCore.QSortFilterProxyModel()
        creators_sort_model.setSourceModel(creators_model)
        creators_view.setModel(creators_sort_model)

        creators_view_layout = QtWidgets.QVBoxLayout(creators_view_widget)
        creators_view_layout.setContentsMargins(0, 0, 0, 0)
        creators_view_layout.addWidget(creator_view_label, 0)
        creators_view_layout.addWidget(creators_view, 1)

        # --- Creator attr defs ---
        creators_attrs_widget = QtWidgets.QWidget(creators_splitter)

        variant_subset_label = QtWidgets.QLabel(
            "Create options", creators_attrs_widget
        )

        variant_subset_widget = QtWidgets.QWidget(creators_attrs_widget)
        # Variant and subset input
        variant_widget = VariantInputsWidget(creators_attrs_widget)

        variant_input = QtWidgets.QLineEdit(variant_widget)
        variant_input.setObjectName("VariantInput")
        variant_input.setToolTip(VARIANT_TOOLTIP)

        variant_hints_btn = QtWidgets.QToolButton(variant_widget)
        variant_hints_btn.setArrowType(QtCore.Qt.DownArrow)
        variant_hints_btn.setIconSize(QtCore.QSize(12, 12))

        variant_hints_menu = QtWidgets.QMenu(variant_widget)
        variant_hints_group = QtWidgets.QActionGroup(variant_hints_menu)

        variant_layout = QtWidgets.QHBoxLayout(variant_widget)
        variant_layout.setContentsMargins(0, 0, 0, 0)
        variant_layout.setSpacing(0)
        variant_layout.addWidget(variant_input, 1)
        variant_layout.addWidget(variant_hints_btn, 0, QtCore.Qt.AlignVCenter)

        subset_name_input = QtWidgets.QLineEdit(variant_subset_widget)
        subset_name_input.setEnabled(False)

        variant_subset_layout = QtWidgets.QFormLayout(variant_subset_widget)
        variant_subset_layout.setContentsMargins(0, 0, 0, 0)
        variant_subset_layout.addRow("Variant", variant_widget)
        variant_subset_layout.addRow("Subset", subset_name_input)

        # Precreate attributes widget
        pre_create_widget = PreCreateWidget(creators_attrs_widget)

        # Create button
        create_btn_wrapper = QtWidgets.QWidget(creators_attrs_widget)
        create_btn = CreateBtn(create_btn_wrapper)
        create_btn.setEnabled(False)

        create_btn_wrap_layout = QtWidgets.QHBoxLayout(create_btn_wrapper)
        create_btn_wrap_layout.setContentsMargins(0, 0, 0, 0)
        create_btn_wrap_layout.addStretch(1)
        create_btn_wrap_layout.addWidget(create_btn, 0)

        creators_attrs_layout = QtWidgets.QVBoxLayout(creators_attrs_widget)
        # NOTE: Match position of '+' button in instances view
        # - use hardcoded border size which is defined in stylesheets
        #   (potentially dangerous)
        # - 10 pixels smaller content of attributes
        borders = 2
        creators_attrs_layout.setContentsMargins(0, 0, 0, 10 + borders)
        creators_attrs_layout.addWidget(variant_subset_label, 0)
        creators_attrs_layout.addWidget(variant_subset_widget, 0)
        creators_attrs_layout.addWidget(pre_create_widget, 1)
        creators_attrs_layout.addWidget(create_btn_wrapper, 0)

        creators_splitter.addWidget(creators_view_widget)
        creators_splitter.addWidget(creators_attrs_widget)
        creators_splitter.setStretchFactor(0, 1)
        creators_splitter.setStretchFactor(1, 1)

        creators_layout = QtWidgets.QVBoxLayout(creators_widget)
        creators_layout.setContentsMargins(0, 0, 0, 0)
        creators_layout.addWidget(creator_short_desc_widget, 0)
        creators_layout.addWidget(attr_separator_widget, 0)
        creators_layout.addWidget(creators_splitter, 1)
        # ------------

        # --- Detailed information about creator ---
        # Detailed description of creator
        # TODO this has no way how can be showed now
        detail_description_widget = QtWidgets.QWidget(main_splitter_widget)

        detail_placoholder_widget = QtWidgets.QWidget(
            detail_description_widget
        )
        detail_placoholder_widget.setAttribute(
            QtCore.Qt.WA_TranslucentBackground
        )

        detail_description_input = QtWidgets.QTextEdit(
            detail_description_widget
        )
        detail_description_input.setObjectName("CreatorDetailedDescription")
        detail_description_input.setTextInteractionFlags(
            QtCore.Qt.TextBrowserInteraction
        )

        detail_description_layout = QtWidgets.QVBoxLayout(
            detail_description_widget
        )
        detail_description_layout.setContentsMargins(0, 0, 0, 0)
        detail_description_layout.setSpacing(0)
        detail_description_layout.addWidget(detail_placoholder_widget, 0)
        detail_description_layout.addWidget(detail_description_input, 1)

        detail_description_widget.setVisible(False)

        # -------------------------------------------
        main_splitter_widget.addWidget(context_widget)
        main_splitter_widget.addWidget(creators_widget)
        main_splitter_widget.addWidget(detail_description_widget)
        main_splitter_widget.setStretchFactor(0, 1)
        main_splitter_widget.setStretchFactor(1, 2)
        main_splitter_widget.setStretchFactor(2, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(main_splitter_widget, 1)

        prereq_timer = QtCore.QTimer()
        prereq_timer.setInterval(50)
        prereq_timer.setSingleShot(True)

        prereq_timer.timeout.connect(self._invalidate_prereq)

        create_btn.clicked.connect(self._on_create)
        variant_widget.resized.connect(self._on_variant_widget_resize)
        variant_input.returnPressed.connect(self._on_create)
        variant_input.textChanged.connect(self._on_variant_change)
        creators_view.selectionModel().currentChanged.connect(
            self._on_creator_item_change
        )
        variant_hints_btn.clicked.connect(self._on_variant_btn_click)
        variant_hints_menu.triggered.connect(self._on_variant_action)
        assets_widget.selection_changed.connect(self._on_asset_change)
        assets_widget.current_context_required.connect(
            self._on_current_session_context_request
        )
        tasks_widget.task_changed.connect(self._on_task_change)
        creator_short_desc_widget.height_changed.connect(
            self._on_description_height_change
        )

        controller.add_plugins_refresh_callback(self._on_plugins_refresh)

        self._main_splitter_widget = main_splitter_widget

        self._creators_splitter = creators_splitter

        self._context_widget = context_widget
        self._assets_widget = assets_widget
        self._tasks_widget = tasks_widget

        self.subset_name_input = subset_name_input

        self.variant_input = variant_input
        self.variant_hints_btn = variant_hints_btn
        self.variant_hints_menu = variant_hints_menu
        self.variant_hints_group = variant_hints_group

        self._creators_model = creators_model
        self._creators_sort_model = creators_sort_model
        self._creators_view = creators_view
        self._create_btn = create_btn

        self._creator_short_desc_widget = creator_short_desc_widget
        self._pre_create_widget = pre_create_widget
        self._attr_separator_widget = attr_separator_widget

        self._detail_placoholder_widget = detail_placoholder_widget
        self._detail_description_widget = detail_description_widget
        self._detail_description_input = detail_description_input

        self._prereq_timer = prereq_timer
        self._first_show = True

    def _emit_message(self, message):
        self._controller.emit_message(message)

    def _context_change_is_enabled(self):
        return self._context_widget.isEnabled()

    def _get_asset_name(self):
        asset_name = None
        if self._context_change_is_enabled():
            asset_name = self._assets_widget.get_selected_asset_name()

        if asset_name is None:
            asset_name = self._asset_name
        return asset_name

    def _get_task_name(self):
        task_name = None
        if self._context_change_is_enabled():
            # Don't use selection of task if asset is not set
            asset_name = self._assets_widget.get_selected_asset_name()
            if asset_name:
                task_name = self._tasks_widget.get_selected_task_name()

        if not task_name:
            task_name = self._task_name
        return task_name

    @property
    def dbcon(self):
        return self._controller.dbcon

    def _set_context_enabled(self, enabled):
        self._assets_widget.set_enabled(enabled)
        self._tasks_widget.set_enabled(enabled)
        check_prereq = self._context_widget.isEnabled() != enabled
        self._context_widget.setEnabled(enabled)
        if check_prereq:
            self._invalidate_prereq()

    def refresh(self):
        # Get context before refresh to keep selection of asset and
        #   task widgets
        asset_name = self._get_asset_name()
        task_name = self._get_task_name()

        self._prereq_available = False

        # Disable context widget so refresh of asset will use context asset
        #   name
        self._set_context_enabled(False)

        self._assets_widget.refresh()

        # Refresh data before update of creators
        self._refresh_asset()
        # Then refresh creators which may trigger callbacks using refreshed
        #   data
        self._refresh_creators()

        self._assets_widget.set_current_asset_name(self._asset_name)
        self._assets_widget.select_asset_by_name(asset_name)
        self._tasks_widget.set_asset_name(asset_name)
        self._tasks_widget.select_task_name(task_name)

        self._invalidate_prereq_deffered()

    def _invalidate_prereq_deffered(self):
        self._prereq_timer.start()

    def _invalidate_prereq(self):
        prereq_available = True
        creator_btn_tooltips = []

        available_creators = self._creators_model.rowCount() > 0
        if available_creators != self._creators_view.isEnabled():
            self._creators_view.setEnabled(available_creators)

        if not available_creators:
            prereq_available = False
            creator_btn_tooltips.append("Creator is not selected")

        if self._context_change_is_enabled() and self._asset_doc is None:
            # QUESTION how to handle invalid asset?
            prereq_available = False
            creator_btn_tooltips.append("Context is not selected")

        if prereq_available != self._prereq_available:
            self._prereq_available = prereq_available

            self._create_btn.setEnabled(prereq_available)

            self.variant_input.setEnabled(prereq_available)
            self.variant_hints_btn.setEnabled(prereq_available)

        tooltip = ""
        if creator_btn_tooltips:
            tooltip = "\n".join(creator_btn_tooltips)
        self._create_btn.setToolTip(tooltip)

        self._on_variant_change()

    def _refresh_asset(self):
        asset_name = self._get_asset_name()

        # Skip if asset did not change
        if self._asset_doc and self._asset_doc["name"] == asset_name:
            return

        # Make sure `_asset_doc` and `_subset_names` variables are reset
        self._asset_doc = None
        self._subset_names = None
        if asset_name is None:
            return

        project_name = self.dbcon.active_project()
        asset_doc = get_asset_by_name(project_name, asset_name)
        self._asset_doc = asset_doc

        if asset_doc:
            asset_id = asset_doc["_id"]
            subset_docs = get_subsets(
                project_name, asset_ids=[asset_id], fields=["name"]
            )
            self._subset_names = {
                subset_doc["name"]
                for subset_doc in subset_docs
            }

        if not asset_doc:
            self.subset_name_input.setText("< Asset is not set >")

    def _refresh_creators(self):
        # Refresh creators and add their families to list
        existing_items = {}
        old_creators = set()
        for row in range(self._creators_model.rowCount()):
            item = self._creators_model.item(row, 0)
            identifier = item.data(CREATOR_IDENTIFIER_ROLE)
            existing_items[identifier] = item
            old_creators.add(identifier)

        # Add new families
        new_creators = set()
        for identifier, creator in self._controller.manual_creators.items():
            # TODO add details about creator
            new_creators.add(identifier)
            if identifier in existing_items:
                item = existing_items[identifier]
            else:
                item = QtGui.QStandardItem()
                item.setFlags(
                    QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
                )
                self._creators_model.appendRow(item)

            label = creator.label or identifier
            item.setData(label, QtCore.Qt.DisplayRole)
            item.setData(identifier, CREATOR_IDENTIFIER_ROLE)
            item.setData(creator.family, FAMILY_ROLE)

        # Remove families that are no more available
        for identifier in (old_creators - new_creators):
            item = existing_items[identifier]
            self._creators_model.takeRow(item.row())

        if self._creators_model.rowCount() < 1:
            return

        self._creators_sort_model.sort(0)
        # Make sure there is a selection
        indexes = self._creators_view.selectedIndexes()
        if not indexes:
            index = self._creators_sort_model.index(0, 0)
            self._creators_view.setCurrentIndex(index)
        else:
            index = indexes[0]

        identifier = index.data(CREATOR_IDENTIFIER_ROLE)

        self._set_creator_by_identifier(identifier)

    def _on_plugins_refresh(self):
        # Trigger refresh only if is visible
        self.refresh()

    def _on_asset_change(self):
        self._refresh_asset()

        asset_name = self._assets_widget.get_selected_asset_name()
        self._tasks_widget.set_asset_name(asset_name)
        if self._context_change_is_enabled():
            self._invalidate_prereq_deffered()

    def _on_task_change(self):
        if self._context_change_is_enabled():
            self._invalidate_prereq_deffered()

    def _on_current_session_context_request(self):
        self._assets_widget.set_current_session_asset()
        if self._task_name:
            self._tasks_widget.select_task_name(self._task_name)

    def _on_description_height_change(self):
        # Use separator's 'y' position as height
        height = self._attr_separator_widget.y()
        self._detail_placoholder_widget.setMinimumHeight(height)
        self._detail_placoholder_widget.setMaximumHeight(height)

    def _on_creator_item_change(self, new_index, _old_index):
        identifier = None
        if new_index.isValid():
            identifier = new_index.data(CREATOR_IDENTIFIER_ROLE)
        self._set_creator_by_identifier(identifier)

    def _set_creator_detailed_text(self, creator):
        if not creator:
            self._detail_description_input.setPlainText("")
            return
        detailed_description = creator.get_detail_description() or ""
        if commonmark:
            html = commonmark.commonmark(detailed_description)
            self._detail_description_input.setHtml(html)
        else:
            self._detail_description_input.setMarkdown(detailed_description)

    def _set_creator_by_identifier(self, identifier):
        creator = self._controller.manual_creators.get(identifier)
        self._set_creator(creator)

    def _set_creator(self, creator):
        self._creator_short_desc_widget.set_plugin(creator)
        self._set_creator_detailed_text(creator)
        self._pre_create_widget.set_plugin(creator)

        self._selected_creator = creator

        if not creator:
            self._set_context_enabled(False)
            return

        if (
            creator.create_allow_context_change
            != self._context_change_is_enabled()
        ):
            self._set_context_enabled(creator.create_allow_context_change)
            self._refresh_asset()

        default_variants = creator.get_default_variants()
        if not default_variants:
            default_variants = ["Main"]

        default_variant = creator.get_default_variant()
        if not default_variant:
            default_variant = default_variants[0]

        for action in tuple(self.variant_hints_menu.actions()):
            self.variant_hints_menu.removeAction(action)
            action.deleteLater()

        for variant in default_variants:
            if variant in SEPARATORS:
                self.variant_hints_menu.addSeparator()
            elif variant:
                self.variant_hints_menu.addAction(variant)

        variant_text = default_variant or "Main"
        # Make sure subset name is updated to new plugin
        if variant_text == self.variant_input.text():
            self._on_variant_change()
        else:
            self.variant_input.setText(variant_text)

    def _on_variant_widget_resize(self):
        self.variant_hints_btn.setFixedHeight(self.variant_input.height())

    def _on_variant_btn_click(self):
        pos = self.variant_hints_btn.rect().bottomLeft()
        point = self.variant_hints_btn.mapToGlobal(pos)
        self.variant_hints_menu.popup(point)

    def _on_variant_action(self, action):
        value = action.text()
        if self.variant_input.text() != value:
            self.variant_input.setText(value)

    def _on_variant_change(self, variant_value=None):
        if not self._prereq_available:
            return

        # This should probably never happen?
        if not self._selected_creator:
            if self.subset_name_input.text():
                self.subset_name_input.setText("")
            return

        if variant_value is None:
            variant_value = self.variant_input.text()

        if not self._compiled_name_pattern.match(variant_value):
            self._create_btn.setEnabled(False)
            self._set_variant_state_property("invalid")
            self.subset_name_input.setText("< Invalid variant >")
            return

        if not self._context_change_is_enabled():
            self._create_btn.setEnabled(True)
            self._set_variant_state_property("")
            self.subset_name_input.setText("< Valid variant >")
            return

        project_name = self._controller.project_name
        task_name = self._get_task_name()

        asset_doc = copy.deepcopy(self._asset_doc)
        # Calculate subset name with Creator plugin
        try:
            subset_name = self._selected_creator.get_subset_name(
                variant_value, task_name, asset_doc, project_name
            )
        except TaskNotSetError:
            self._create_btn.setEnabled(False)
            self._set_variant_state_property("invalid")
            self.subset_name_input.setText("< Missing task >")
            return

        self.subset_name_input.setText(subset_name)

        self._create_btn.setEnabled(True)
        self._validate_subset_name(subset_name, variant_value)

    def _validate_subset_name(self, subset_name, variant_value):
        # Get all subsets of the current asset
        if self._subset_names:
            existing_subset_names = set(self._subset_names)
        else:
            existing_subset_names = set()
        existing_subset_names_low = set(
            _name.lower()
            for _name in existing_subset_names
        )

        # Replace
        compare_regex = re.compile(re.sub(
            variant_value, "(.+)", subset_name, flags=re.IGNORECASE
        ))
        variant_hints = set()
        if variant_value:
            for _name in existing_subset_names:
                _result = compare_regex.search(_name)
                if _result:
                    variant_hints |= set(_result.groups())

        # Remove previous hints from menu
        for action in tuple(self.variant_hints_group.actions()):
            self.variant_hints_group.removeAction(action)
            self.variant_hints_menu.removeAction(action)
            action.deleteLater()

        # Add separator if there are hints and menu already has actions
        if variant_hints and self.variant_hints_menu.actions():
            self.variant_hints_menu.addSeparator()

        # Add hints to actions
        for variant_hint in variant_hints:
            action = self.variant_hints_menu.addAction(variant_hint)
            self.variant_hints_group.addAction(action)

        # Indicate subset existence
        if not variant_value:
            property_value = "empty"

        elif subset_name.lower() in existing_subset_names_low:
            # validate existence of subset name with lowered text
            #   - "renderMain" vs. "rendermain" mean same path item for
            #   windows
            property_value = "exists"
        else:
            property_value = "new"

        self._set_variant_state_property(property_value)

        variant_is_valid = variant_value.strip() != ""
        if variant_is_valid != self._create_btn.isEnabled():
            self._create_btn.setEnabled(variant_is_valid)

    def _set_variant_state_property(self, state):
        current_value = self.variant_input.property("state")
        if current_value != state:
            self.variant_input.setProperty("state", state)
            self.variant_input.style().polish(self.variant_input)

    def _on_first_show(self):
        width = self.width()
        part = int(width / 7)

        self._main_splitter_widget.setSizes(
            [part * 2, part * 4, width - (part * 6)]
        )
        self._creators_splitter.setSizes([part * 2, part * 2])

    def showEvent(self, event):
        super(CreateWidget, self).showEvent(event)
        if self._first_show:
            self._first_show = False
            self._on_first_show()

    def _on_create(self):
        indexes = self._creators_view.selectedIndexes()
        if not indexes or len(indexes) > 1:
            return

        if not self._create_btn.isEnabled():
            return

        index = indexes[0]
        creator_label = index.data(QtCore.Qt.DisplayRole)
        creator_identifier = index.data(CREATOR_IDENTIFIER_ROLE)
        family = index.data(FAMILY_ROLE)
        variant = self.variant_input.text()
        # Care about subset name only if context change is enabled
        subset_name = None
        asset_name = None
        task_name = None
        if self._context_change_is_enabled():
            subset_name = self.subset_name_input.text()
            asset_name = self._get_asset_name()
            task_name = self._get_task_name()

        pre_create_data = self._pre_create_widget.current_value()
        # Where to define these data?
        # - what data show be stored?
        instance_data = {
            "asset": asset_name,
            "task": task_name,
            "variant": variant,
            "family": family
        }

        error_msg = None
        formatted_traceback = None
        try:
            self._controller.create(
                creator_identifier,
                subset_name,
                instance_data,
                pre_create_data
            )

        except CreatorError as exc:
            error_msg = str(exc)

        # Use bare except because some hosts raise their exceptions that
        #   do not inherit from python's `BaseException`
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            formatted_traceback = "".join(traceback.format_exception(
                exc_type, exc_value, exc_traceback
            ))
            error_msg = str(exc_value)

        if error_msg is None:
            self._set_creator(self._selected_creator)
            self._emit_message("Creation finished...")
        else:
            box = CreateErrorMessageBox(
                creator_label,
                subset_name,
                asset_name,
                error_msg,
                formatted_traceback,
                parent=self
            )
            box.show()
            # Store dialog so is not garbage collected before is shown
            self._message_dialog = box
