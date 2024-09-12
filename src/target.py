from codefile import CodeFile
from common import Language
from git import Blob, Commit, Repo, Tree
from patch import Patch


class Target:
    def __init__(self, repo_path: str, commit_id: str, language: Language):
        self.repo = Repo(repo_path)
        self.commit: Commit = self.repo.commit(commit_id)
        self.language = language

    @property
    def code_file_suffix(self) -> str:
        if self.language == Language.JAVA:
            return ".java"
        else:
            return ".c"

    @staticmethod
    def get_all_blobs(root_tree: Tree) -> list[Blob]:
        all_blobs = []
        for blob in root_tree.blobs:
            all_blobs.append(blob)
        for tree in root_tree.trees:
            all_blobs.extend(Target.get_all_blobs(tree))
        return all_blobs

    def get_pre_code_blobs(self) -> list[Blob]:
        blobs = []
        for blob in self.get_all_blobs(self.commit.parents[0].tree):
            assert isinstance(blob.path, str)
            if "test/" in blob.path:
                continue
            if blob.name.endswith(self.code_file_suffix):
                blobs.append(blob)
        return blobs

    def get_post_code_blobs(self) -> list[Blob]:
        blobs = []
        for blob in self.get_all_blobs(self.commit.tree):
            assert isinstance(blob.path, str)
            if "test/" in blob.path:
                continue
            if blob.name.endswith(self.code_file_suffix):
                blobs.append(blob)
        return blobs

    def get_code_files(self, patch: Patch) -> list[CodeFile]:
        all_blobs = self.get_all_blobs(self.commit.tree)
        result = []
        for blob in all_blobs:
            assert isinstance(blob.path, str)
            if "test/" in blob.path:
                continue
            if not blob.name.endswith(self.code_file_suffix):
                continue
            if blob.path in patch.changed_files_path_set:
                file = CodeFile(blob.path, blob.data_stream.read().decode())
                result.append(file)
        return result
