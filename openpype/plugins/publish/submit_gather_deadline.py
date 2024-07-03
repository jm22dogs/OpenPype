import os
import getpass

import pyblish.api

from openpype.pipeline import legacy_io

class GatherSubmitDeadline(pyblish.api.InstancePlugin):
    """Submit gather to deadline."""

    label = "Submit gather to Deadline"
    order = pyblish.api.IntegratorOrder + 0.1
    hosts = ["traypublisher"]
    # families = ["render.farm", "prerender.farm"]
    families = ["gather.farm"]
    # families = []
    optional = True
    targets = ["local"]

    # presets
    priority = 50
    chunk_size = 1
    concurrent_tasks = 1
    group = ""
    department = ""
    use_gpu = False
    env_allowed_keys = []
    env_search_replace_values = {}

    def process(self, instance):
        instance.data["toBeRenderedOn"] = "deadline"
        families = instance.data["families"]

        context = instance.context

        deadline_url = instance.context.data["defaultDeadline"]
        deadline_url = instance.data.get("deadlineUrl", deadline_url)
        assert deadline_url, "Requires Deadline Webservice URL"

        self.deadline_url = f"{deadline_url}/api/jobs"
        self._comment = context.data.get("comment", "")
        self._deadline_user = context.data.get( "deadlineUser", getpass.getuser())

        # get output path
        render_path = instance.data["publishDir"]
        self.log.info(f">>>> Render path is {render_path}")
        context.data["currentFile"] = ""

        legacy_io.Session["AVALON_TASK"] = instance.data['task']
        legacy_io.Session["AVALON_ASSET"] = instance.data['asset']


        batch = f"{instance.data['project']} - {instance.data['asset']} - "
        batch += f"{instance.data['task']} - {instance.data['subset']} - "
        batch += f"v{instance.data['version']:03}"

        instance.data["deadlineSubmissionJob"] = {
            "Props" : {
                "Batch": batch,
                "User": context.data.get("deadlineUser", getpass.getuser()),
                }
        }
        
        instance.data["farm"] = True
        instance.data["outputDir"] = os.path.dirname(
            render_path).replace("\\", "/")
        instance.data["publishJobState"] = "Suspended"
        instance.context.data["version"] = instance.data["version"]

        for k, v in instance.data["published_representations"].items():
            self.expected_files(
                instance,
                v["published_files"][0],
                instance.data["frameStart"],
                instance.data["frameEnd"]
            )

        # self.redefine_families(instance, families)
    
    def expected_files(
        self,
        instance,
        path,
        start_frame,
        end_frame
    ):
        """ Create expected files in instance data """

        if not instance.data.get("expectedFiles"):
            instance.data["expectedFiles"] = []

        dirname = os.path.dirname(path)
        file = os.path.basename(path)

        if "#" in file:
            pparts = file.split("#")
            padding = "%0{}d".format(len(pparts) - 1)
            file = pparts[0] + padding + pparts[-1]

        if "%" not in file:
            instance.data["expectedFiles"].append(path)
            return

        if instance.data.get("slate"):
            start_frame -= 1

        for i in range(start_frame, (end_frame + 1)):
            instance.data["expectedFiles"].append(
                os.path.join(dirname, (file % i)).replace("\\", "/"))

    @staticmethod
    def redefine_families(instance, families):
        """This method changes the family into 'write' for nuke so it is that
        it is not recogniced by following plugins and thus they are turned off."""

        if "render.farm" in families:
            instance.data['family'] = 'write'
            families.insert(0, "render2d")
        elif "prerender.farm" in families:
            instance.data['family'] = 'write'
            families.insert(0, "prerender")
        elif "gather.farm" in families:
            instance.data['family'] = 'ignore_ftrack_local'
            families.insert(0, "gather.farm")

        instance.data["families"] = families

