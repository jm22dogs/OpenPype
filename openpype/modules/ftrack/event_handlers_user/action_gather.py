import json
import os
import re
import platform
import traceback

import openpype.lib

import openpype.hosts
import openpype.hosts.traypublisher
import openpype.hosts.traypublisher.api
from qtpy import QtWidgets

import openpype.modules
from openpype.pipeline import install_host
from openpype.modules.ftrack.lib import BaseAction, statics_icon

from openpype.client import (
    get_asset_by_name,
    get_subset_by_name,
    get_representation_by_name,
    get_last_version_by_subset_id,
    get_version_by_name
)

import openpype.pipeline
from openpype.settings import (
    get_system_settings,
    get_project_settings
)

import openpype
import openpype.tools
import openpype.tools.traypublisher


class GatherAction(BaseAction):
    """Gather selected Assetversions for publish into delivery family."""

    identifier = "gather.versions"
    label = "Gather"
    description = "Gather version"
    icon = statics_icon("ftrack", "action_icons", "Gather.png")

    type = "Application"

    exclude_component_list = [ "review", "thumbnail" ]

    def __init__(self, *args, **kwargs):
        self.assetversions = list()
        self.project_name = None
        super().__init__(*args, **kwargs)

    def discover(self, session, entities, event):
        etype = entities[0].entity_type

        if etype == "AssetVersionList" or etype == "AssetVersion":
            return True
        else:
            return False

    def interface(self, session, entities, event):
        if event['data'].get('values', {}):
            return
        
        self.assetversions = self.get_all_assetversions(session, entities)
        self.project_name = self.assetversions[0]["project"]["full_name"]

        items = [{
            "type": "label",
            "value": "<h1><b>Select Representations to Gather:</b></h1>"
        }]

        try:
            for assetversion in self.assetversions:
                enum_data = []
                components = self.get_all_available_components_for_assetversion(session, assetversion)
                for comp in components:
                    enum_data.append({
                        "label": comp,
                        "value": comp
                    })
                enum_data = sorted(enum_data, key = lambda d: not "exr"==d["label"])
                if not enum_data:
                    raise IndexError("Failed to fetch any components")
                item_name = "{} - {} v{}".format(
                    assetversion["asset"]["parent"]["name"],
                    assetversion["asset"]["name"],
                    str(assetversion["version"]).zfill(3)
                )
                items.extend(
                    [
                        {
                            "type": "label",
                            "value": "<b>{}</b>".format(item_name)
                        },
                        {
                            "label": "<span style=\"font-size: 7pt;\">Representation</span>",
                            "type": "enumerator",
                            "name": assetversion["id"],
                            "data": enum_data,
                            "value": enum_data[0]["value"]
                        }
                    ]
                )
            
            return {
                "type": "form",
                "title": "Gather Action",
                "items": items,
                "submit_button_label": "Gather",
                "width": 500,
                "height": 600
            }
    
        except:
            self.log.error(traceback.format_exc())
            return {"success": False, "message": traceback.format_exc().splitlines()[-1]}

    def launch(self, session, entities, event):

        user_values = event["data"].get("values", None)

        if user_values is None:
            return
        
        self.log.info("Sumbitted choices: {}".format(user_values))

        self.project_name = self.assetversions[0]["project"]["full_name"]

        host = openpype.hosts.traypublisher.api.TrayPublisherHost()
        install_host(host)
        host.set_project_name(self.project_name)
        self.log.info("Project Name: was set: '{}'".format(self.project_name))

        create_context = openpype.pipeline.create.CreateContext(host,
                                                                headless=True,
                                                                discover_publish_plugins=True,
                                                                reset=True)

        for instance in list(create_context.instances):
            create_plugin = create_context.creators.get(
                instance.creator_identifier
            )
            create_plugin.remove_instances([instance])

        for version in self.assetversions:
            current_links = len(version["outgoing_links"])
            if current_links > 0:
                self.log.debug("This asset has already linked delivery versions attached, skipping delivery for now...")
                continue
            self.target_asset_name = "{}_delivery".format(version["asset"]["name"])
            self.publisher_start(session, create_context, version, user_values)

        if not create_context.instances:
            msg = "No valid instances could be gathered, aborting..."
            self.log.debug(msg)
            return {
                "success": False,
                "message": msg
            }

        app_instance = QtWidgets.QApplication.instance()
        if app_instance is None:
            app_instance = QtWidgets.QApplication([])
        if platform.system().lower() == "windows":
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                u"traypublisher"
            )
        
        window = openpype.tools.traypublisher.window.TrayPublishWindow()
        window._overlay_widget._set_project(self.project_name)
        # window.set_context_label("{} - GATHER DELIVERIES".format(self.project_name))
        window.show()
        app_instance.exec_()

        return True

    def get_all_available_components_for_assetversion(self, session, assetversion):
        component_list = []
        components = session.query("select name from Component where version_id is '{}'".format(assetversion["id"])).all()
        for comp in components:
            valid = True
            for excl in self.exclude_component_list:
                if comp["name"].find(excl) >= 0:
                    valid = False
                    break
            if valid:
                component_list.append(comp["name"])
            
        return list(set(component_list))

    def get_files_from_repre(self, repre, version):
        files = []
        for file in repre["files"]:
            files.append(file["path"].format(**repre["context"]))
        repre_start = int(re.findall(r'\d+$', os.path.splitext(files[0])[0])[0])
        version_start = int(version["data"]["frameStart"]) - int(version["data"]["handleStart"])
        self.log.debug("Detected frames: repre_start:{} <-> version_start:{}".format(repre_start, version_start))
        if repre_start < version_start:
            files.pop(0)
        return files

    def get_all_assetversions(self, session, entities):

        result = []

        for entity in entities:
            etype = entity.entity_type

            if etype == "FileComponent":
                query = "select id, asset_id, task.name, task_id, version, asset.name, asset.parent.name, outgoing_links from AssetVersion where components any (id='{0}')".format(entity["id"])
                for assetversion in session.query(query).all():
                    result.append(assetversion)

            elif etype == "AssetVersion":
                query = "select id, asset_id, task.name, task_id, version, asset.name, asset.parent.name, outgoing_links from AssetVersion where id is '{0}'".format(entity["id"])
                for assetversion in session.query(query).all():
                    result.append(assetversion)

            elif etype == "AssetVersionList":
                query = "select id, asset_id, task.name, task_id, version, asset.name, asset.parent.name, outgoing_links from AssetVersion where lists any (id='{0}')".format(entity["id"])
                for assetversion in session.query(query).all():
                    result.append(assetversion)
            
            else:
                message = "\"{}\" entity type is not implemented yet.".format(entity.entity_type)
                self.log.error(message)
        
        return result

    def get_comment_from_notes(self, session, entity):
        client_tag = "For Client"
        notes = []
        query = "select content, date, note_label_links.label.name from Note where parent_id is '{0}' and note_label_links.label.name is '{1}'".format(entity["id"],
                                                                                                                                           client_tag)
        for note in session.query(query).all():
            notes.append(note)

        if not notes:
            return None
        
        notes_sorted = list(sorted(notes, key=lambda d: d["date"]))
        intent_value = None
        result = {
            "comment": "",
            "intent": {
                "label": "",
                "value": ""
            }
        }
        for label in notes_sorted[-1]["note_label_links"]:
            if label["label"]["name"] != client_tag:
                intent_value = label["label"]["name"]
        
        if intent_value:
            system_settings = get_system_settings()
            intent_settings = system_settings["modules"]["ftrack"]["intent"]["items"]
            for key, value in intent_settings.items():
                if key == intent_value:
                    result["intent"]["label"] = value
                    result["intent"]["value"] = key

        result["comment"] = notes_sorted[-1]["content"]

        return result

    def get_all_available_tasks(self, session, version):
        tasks = {}
        query = "select id, name, type.name from Task where parent_id is '{}'".format(version["asset"]["parent"]["id"])
        for task in session.query(query).all():
            tasks.update({ task["name"]: task["type"]["name"] })
        return tasks

    def publisher_start(self, session, create_context, version, user_values):
        family = "delivery"
        project_name = self.project_name
        project_id = version["project_id"]
        version_name = int(version["version"])
        subset_name = version["asset"]["name"]
        asset_name = version["asset"]["parent"]["name"]
        repre_name = user_values[version["id"]]
        settings = get_project_settings(project_name)["ftrack"]["user_handlers"]["gather_action"]

        self.log.debug("Asset Name for subset '{}' is '{}'".format(subset_name, asset_name))

        asset_doc = get_asset_by_name(
            project_name,
            asset_name
        )
        subset_doc = get_subset_by_name(
            project_name,
            subset_name,
            asset_doc["_id"]
        )
        # version_doc = get_last_version_by_subset_id(
        #     project_name,
        #     subset_doc["_id"]
        # )
        version_doc = get_version_by_name(
            project_name,
            version_name,
            subset_doc["_id"]
        )
        repre_doc = get_representation_by_name(
            project_name,
            repre_name,
            version_doc["_id"]
        )

        repre_files = self.get_files_from_repre(repre_doc, version_doc)

        computed_asset = repre_doc["context"]["asset"]

        if len(settings["missing_task_override"]) > 0:
            task_override = settings["missing_task_override"][0]
        else:
            task_override = ""
        avail_tasks = self.get_all_available_tasks(session, version)
        avail_tasks.update({ "": task_override })
        self.log.debug("Available tasks for current asset:\n{}".format(json.dumps(avail_tasks, indent=4, default=str)))

        try:
            detected_task_name = repre_doc["context"]["task"]["name"]
            if detected_task_name not in avail_tasks.keys():
                self.log.debug("Task type not found in available tasks.")
                detected_task_name = ""
        except:
            self.log.debug("Failed to fetch task!")
            detected_task_name = ""


        self.log.debug("Detected task name is '{}'".format(detected_task_name))
        self.log.debug("Computed task type is '{}'".format(avail_tasks[detected_task_name]))

        computed_variant = repre_doc["context"]["subset"].lower().replace(
            repre_doc["context"]["family"],
            ""
        ).replace(
            detected_task_name.lower(),
            ""
        ).capitalize()
        self.log.debug("Computed variant is '{}'".format(computed_variant))

        subset_format_data = {
            "asset": computed_asset,
            "family": family,
            "task": avail_tasks[detected_task_name],
            "variant": computed_variant
        }
        computed_subset = settings["subset_name_template"].format_map(subset_format_data)
        self.log.debug("Computed subset is '{}'".format(computed_subset))

        computed_name = computed_asset + "_" + computed_subset
        self.log.debug("Computed instance name is '{}'".format(computed_name))

        delivery_suffix = settings["delivery_asset_suffix"]
        if delivery_suffix:
            delivery_suffix = "_" + delivery_suffix

        delivery_instance = {
            "project": project_name,
            "family": family,
            "families": [family],
            "subset": computed_subset,
            "variant": avail_tasks[detected_task_name] + computed_variant,
            "asset": repre_doc["context"]["asset"],
            "task": detected_task_name,
            "name": computed_name,
            "label": computed_name,
            "delivery_root_name": settings["delivery_root"],
            "delivery_project_name": project_name,
            "delivery_project_id": project_id,
            "delivery_representation_name": repre_doc["name"],
            "delivery_representation_files": repre_files,
            "delivery_asset_name": asset_name + delivery_suffix,
            "delivery_task_id": str(version["task_id"]) if str(version["task_id"]) != "NOT_SET" else None,
            "delivery_ftrack_source_id": version["id"]
        }

        note = self.get_comment_from_notes(session, version)
        if note:
            delivery_instance.update(note)

        self.log.debug("Instance data to be created: {}".format(
            json.dumps(delivery_instance, indent=4, default=str)))

        publish_file_list = [item.to_dict() for item in openpype.lib.FileDefItem.from_paths(
            repre_files, allow_sequences=True)]
        
        create_context.create(
            "settings_{}".format(family),
            computed_subset,
            delivery_instance,
            pre_create_data={
                "representation_files": publish_file_list,
                "reviewable": publish_file_list[0],
            }
        )

    
def register(session):
    '''Register plugin. Called when used as an plugin.'''

    GatherAction(session).register()
