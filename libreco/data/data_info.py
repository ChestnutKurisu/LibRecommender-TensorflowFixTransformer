"""Class for Storing Various Data Information."""
import inspect
import json
import os
from collections import namedtuple
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from numpy.random import default_rng

from ..feature import check_oov, compute_sparse_feat_indices, interaction_consumed

Feature = namedtuple("Feature", ["name", "index"])

EmptyFeature = Feature(name=[], index=[])


# noinspection PyUnresolvedReferences
@dataclass
class MultiSparseInfo:
    """:class:`dataclass` object for storing Multi-sparse features information.

    A group of multi-sparse features are considered a "field".
    e.g. ["genre1", "genre2", "genre3"] form a field "genre".
    So this object contains fields' offset, field's length and fields' oov.
    Since features belong to the same field share one oov.

    Attributes
    ----------
    field_offset : list of int
        All multi-sparse fields' offset in all expanded sparse features.
    field_len: list of int
        All multi-sparse fields' sizes.
    feat_oov: numpy.ndarray
        All multi-sparse fields' oov.
    """

    __slots__ = ("field_offset", "field_len", "feat_oov")

    field_offset: Iterable[int]
    field_len: Iterable[int]
    feat_oov: np.ndarray


class DataInfo:
    """Object for storing and updating indices and features information.

    Parameters
    ----------
    col_name_mapping : dict of {dict : int} or None, default: None
        Column name to index mapping, which has the format: ``{column_family_name: {column_name: index}}``.
        If no such family, the default format would be: {column_family_name: {[]: []}
    interaction_data : pandas.DataFrame or None, default: None
        Data contains ``user``, ``item`` and ``label`` columns
    user_sparse_unique : numpy.ndarray or None, default: None
        Unique sparse features for all users in train data.
    user_dense_unique : numpy.ndarray or None, default: None
        Unique dense features for all users in train data.
    item_sparse_unique : numpy.ndarray or None, default: None
        Unique sparse features for all items in train data.
    item_dense_unique : numpy.ndarray or None, default: None
        Unique dense features for all items in train data.
    user_indices : numpy.ndarray or None, default: None
        Mapped inner user indices from train data.
    item_indices : numpy.ndarray or None, default: None
        Mapped inner item indices from train data.
    user_unique_vals : numpy.ndarray or None, default: None
        All the unique users in train data.
    item_unique_vals : numpy.ndarray or None, default: None
        All the unique items in train data.
    sparse_unique_vals : dict of {str : numpy.ndarray} or None, default: None
        All sparse features' unique values.
    sparse_offset : numpy.ndarray or None, default: None
        Offset for each sparse feature in all sparse values. Often used in the ``embedding`` layer.
    sparse_oov : numpy.ndarray or None, default: None
        Out-of-vocabulary place for each sparse feature. Often used in cold-start.
    multi_sparse_unique_vals : dict of {str : numpy.ndarray} or None, default: None
        All multi-sparse features' unique values.
    multi_sparse_combine_info : MultiSparseInfo or None, default: None
        Multi-sparse field information.

    Attributes
    ----------
    col_name_mapping : dict of {dict : int} or None
        See Parameters
    user_consumed : dict of {int, list}
        Every users' consumed items in train data.
    item_consumed : dict of {int, list}
        Every items' consumed users in train data.
    popular_items : list
        A number of popular items in train data. Often used in cold-start.

    See Also
    --------
    MultiSparseInfo
    """

    def __init__(
        self,
        col_name_mapping=None,
        interaction_data=None,
        user_sparse_unique=None,
        user_dense_unique=None,
        item_sparse_unique=None,
        item_dense_unique=None,
        user_indices=None,
        item_indices=None,
        user_unique_vals=None,
        item_unique_vals=None,
        sparse_unique_vals=None,
        sparse_offset=None,
        sparse_oov=None,
        multi_sparse_unique_vals=None,
        multi_sparse_combine_info=None,
    ):
        self.col_name_mapping = col_name_mapping
        self.interaction_data = interaction_data
        self.user_sparse_unique = user_sparse_unique
        self.user_dense_unique = user_dense_unique
        self.item_sparse_unique = item_sparse_unique
        self.item_dense_unique = item_dense_unique
        self.user_consumed, self.item_consumed = interaction_consumed(
            user_indices, item_indices
        )
        self.user_unique_vals = user_unique_vals
        self.item_unique_vals = item_unique_vals
        self.sparse_unique_vals = sparse_unique_vals
        self.sparse_unique_idxs = DataInfo.map_unique_vals(sparse_unique_vals)
        self.sparse_offset = sparse_offset
        self.sparse_oov = sparse_oov
        self.multi_sparse_unique_vals = multi_sparse_unique_vals
        self.multi_sparse_unique_idxs = DataInfo.map_unique_vals(
            multi_sparse_unique_vals
        )
        self.multi_sparse_combine_info = multi_sparse_combine_info
        # Numpy doc states that it is recommended to use new random API
        # https://numpy.org/doc/stable/reference/random/index.html
        self.np_rng = default_rng()
        self._n_users = None
        self._n_items = None
        self._user2id = None
        self._item2id = None
        self._id2user = None
        self._id2item = None
        self._data_size = None
        self.popular_items = None
        # store old info for rebuild models
        self.old_n_users = None
        self.old_n_items = None
        self.old_sparse_len = None
        self.old_sparse_oov = None
        self.old_sparse_offset = None
        self.all_args = locals()
        self.add_oov()
        if self.popular_items is None:
            self.set_popular_items(100)

    @staticmethod
    def map_unique_vals(sparse_unique_vals):
        if sparse_unique_vals is None:
            return None
        res = dict()
        for col in sparse_unique_vals:
            vals = sparse_unique_vals[col]
            size = len(vals)
            res[col] = dict(zip(vals, range(size)))
        return res

    @property
    def global_mean(self):
        """Mean value of all labels in `rating` task."""
        return self.interaction_data.label.mean()

    @property
    def min_max_rating(self):
        """Min and max value of all labels in `rating` task."""
        return self.interaction_data.label.min(), self.interaction_data.label.max()

    @property
    def sparse_col(self):
        """Sparse column name to index mapping."""
        if not self.col_name_mapping or not self.col_name_mapping["sparse_col"]:
            return EmptyFeature
        return Feature(
            name=list(self.col_name_mapping["sparse_col"].keys()),
            index=list(self.col_name_mapping["sparse_col"].values()),
        )

    @property
    def dense_col(self):
        """Dense column name to index mapping."""
        if not self.col_name_mapping or not self.col_name_mapping["dense_col"]:
            return EmptyFeature
        return Feature(
            name=list(self.col_name_mapping["dense_col"].keys()),
            index=list(self.col_name_mapping["dense_col"].values()),
        )

    @property
    def user_sparse_col(self):
        """User sparse column name to index mapping."""
        if not self.col_name_mapping or not self.col_name_mapping["user_sparse_col"]:
            return EmptyFeature
        return Feature(
            name=list(self.col_name_mapping["user_sparse_col"].keys()),
            index=list(self.col_name_mapping["user_sparse_col"].values()),
        )

    @property
    def user_dense_col(self):
        """User dense column name to index mapping."""
        if not self.col_name_mapping or not self.col_name_mapping["user_dense_col"]:
            return EmptyFeature
        return Feature(
            name=list(self.col_name_mapping["user_dense_col"].keys()),
            index=list(self.col_name_mapping["user_dense_col"].values()),
        )

    @property
    def item_sparse_col(self):
        """Item sparse column name to index mapping."""
        if not self.col_name_mapping or not self.col_name_mapping["item_sparse_col"]:
            return EmptyFeature
        return Feature(
            name=list(self.col_name_mapping["item_sparse_col"].keys()),
            index=list(self.col_name_mapping["item_sparse_col"].values()),
        )

    @property
    def item_dense_col(self):
        """Item dense column name to index mapping."""
        if not self.col_name_mapping or not self.col_name_mapping["item_dense_col"]:
            return EmptyFeature
        return Feature(
            name=list(self.col_name_mapping["item_dense_col"].keys()),
            index=list(self.col_name_mapping["item_dense_col"].values()),
        )

    @property
    def user_col(self):
        """All the user column names, including sparse and dense."""
        if not self.col_name_mapping:
            return []
        # will be sorted by key
        return (
            self.col_name_mapping["user_sparse_col"]
            .keys()
            .__or__(self.col_name_mapping["user_dense_col"].keys())
        )

    @property
    def item_col(self):
        """All the item column names, including sparse and dense."""
        if not self.col_name_mapping:
            return []
        # will be sorted by key
        return (
            self.col_name_mapping["item_sparse_col"]
            .keys()
            .__or__(self.col_name_mapping["item_dense_col"].keys())
        )

    @property
    def n_users(self):
        """Number of users in train data."""
        if self._n_users is None:
            self._n_users = len(self.user_unique_vals)
        return self._n_users

    @property
    def n_items(self):
        """Number of items in train data."""
        if self._n_items is None:
            self._n_items = len(self.item_unique_vals)
        return self._n_items

    @property
    def user2id(self):
        """User original id to inner id mapping."""
        if self._user2id is None:
            self._user2id = dict(zip(self.user_unique_vals, range(self.n_users)))
        return self._user2id

    @property
    def item2id(self):
        """Item original id to inner id mapping."""
        if self._item2id is None:
            self._item2id = dict(zip(self.item_unique_vals, range(self.n_items)))
        return self._item2id

    @property
    def id2user(self):
        """User inner id to original id mapping."""
        if self._id2user is None:
            self._id2user = {j: user for user, j in self.user2id.items()}
        return self._id2user

    @property
    def id2item(self):
        """User inner id to original id mapping."""
        if self._id2item is None:
            self._id2item = {j: item for item, j in self.item2id.items()}
        return self._id2item

    @property
    def data_size(self):
        """Train data size."""
        if self._data_size is None:
            self._data_size = len(self.interaction_data)
        return self._data_size

    def __repr__(self):
        r"""Output train data information: \"n_users, n_items, data density\"."""
        n_users = self.n_users
        n_items = self.n_items
        n_labels = len(self.interaction_data)
        return "n_users: %d, n_items: %d, data density: %.4f %%" % (
            n_users,
            n_items,
            100 * n_labels / (n_users * n_items),
        )

    def get_indexed_interaction(self):
        data = self.interaction_data.copy()
        data.user = data.user.map(self.user2id)
        data.item = data.item.map(self.item2id)
        if data.user.isnull().any():
            data["user"].fillna(self.n_users, inplace=True)
            data["user"] = data["user"].astype("int")
        if data.item.isnull().any():
            data["item"].fillna(self.n_items, inplace=True)
            data["item"] = data["item"].astype("int")
        return data

    def update_consumed(self, user_indices, item_indices, merge):
        if merge:
            old_data = self.get_indexed_interaction()
            user_indices = np.append(old_data.user.to_numpy(), user_indices)
            item_indices = np.append(old_data.item.to_numpy(), item_indices)
        self.user_consumed, self.item_consumed = interaction_consumed(
            user_indices, item_indices
        )
        return user_indices, item_indices

    def reset_property(self):
        self._n_users = None
        self._n_items = None
        self._user2id = None
        self._item2id = None
        self._id2user = None
        self._id2item = None
        self._data_size = None

    def store_old_info(self):
        self.old_n_users = self.n_users
        self.old_n_items = self.n_items
        if (
            self.sparse_unique_vals is not None
            or self.multi_sparse_unique_vals is not None
        ):
            self.old_sparse_len = list()
            self.old_sparse_oov = list()
            self.old_sparse_offset = list()
            for i, col in enumerate(self.sparse_col.name):
                if (
                    self.sparse_unique_vals is not None
                    and col in self.sparse_unique_vals
                ):
                    self.old_sparse_len.append(len(self.sparse_unique_vals[col]))
                    self.old_sparse_oov.append(self.sparse_oov[i])
                    self.old_sparse_offset.append(self.sparse_offset[i])
                elif (
                    self.multi_sparse_unique_vals is not None
                    and col in self.multi_sparse_unique_vals
                ):
                    self.old_sparse_len.append(len(self.multi_sparse_unique_vals[col]))
                    self.old_sparse_oov.append(self.sparse_oov[i])
                    self.old_sparse_offset.append(self.sparse_offset[i])
                elif (
                    self.multi_sparse_unique_vals is not None
                    and col in self.col_name_mapping["multi_sparse"]
                ):
                    main_name = self.col_name_mapping["multi_sparse"][col]
                    pos = self.sparse_col.name.index(main_name)
                    # multi_sparse case, second to last is redundant.
                    # Used in rebuild_tf_model(), rebuild_torch_model()
                    self.old_sparse_len.append(-1)
                    # self.old_sparse_oov.append(self.sparse_oov[pos])
                    self.old_sparse_offset.append(self.sparse_offset[pos])

    def expand_sparse_unique_vals_and_matrix(self, data):
        self.store_old_info()
        self.reset_property()

        user_diff = np.setdiff1d(data.user.to_numpy(), self.user_unique_vals)
        if len(user_diff) > 0:
            self.user_unique_vals = np.append(self.user_unique_vals, user_diff)
            self.extend_unique_matrix("user", len(user_diff))

        item_diff = np.setdiff1d(data.item.to_numpy(), self.item_unique_vals)
        if len(item_diff) > 0:
            self.item_unique_vals = np.append(self.item_unique_vals, item_diff)
            self.extend_unique_matrix("item", len(item_diff))

        def update_sparse_unique(unique_dicts, unique_idxs):
            for sparse_col in unique_dicts:
                unique_vals = list(unique_dicts[sparse_col])
                sparse_diff = np.setdiff1d(data[sparse_col].to_numpy(), unique_vals)
                if len(sparse_diff) > 0:
                    unique_vals = np.append(unique_vals, sparse_diff)
                    unique_dicts[sparse_col] = unique_vals
                    size = len(unique_vals)
                    unique_idxs[sparse_col] = dict(zip(unique_vals, range(size)))

        if self.sparse_unique_vals is not None:
            update_sparse_unique(self.sparse_unique_vals, self.sparse_unique_idxs)
        if self.multi_sparse_unique_vals is not None:
            update_sparse_unique(
                self.multi_sparse_unique_vals, self.multi_sparse_unique_idxs
            )

    def extend_unique_matrix(self, mode, diff_num):
        if mode == "user":
            if self.user_sparse_unique is not None:
                new_users = np.zeros(
                    [diff_num, self.user_sparse_unique.shape[1]],
                    dtype=self.user_sparse_unique.dtype,
                )
                # exclude last oov unique values
                self.user_sparse_unique = np.vstack(
                    [self.user_sparse_unique[:-1], new_users]
                )
            if self.user_dense_unique is not None:
                new_users = np.zeros(
                    [diff_num, self.user_dense_unique.shape[1]],
                    dtype=self.user_dense_unique.dtype,
                )
                self.user_dense_unique = np.vstack(
                    [self.user_dense_unique[:-1], new_users]
                )
        elif mode == "item":
            if self.item_sparse_unique is not None:
                new_items = np.zeros(
                    [diff_num, self.item_sparse_unique.shape[1]],
                    dtype=self.item_sparse_unique.dtype,
                )
                self.item_sparse_unique = np.vstack(
                    [self.item_sparse_unique[:-1], new_items]
                )
            if self.item_dense_unique is not None:
                new_items = np.zeros(
                    [diff_num, self.item_dense_unique.shape[1]],
                    dtype=self.item_dense_unique.dtype,
                )
                self.item_dense_unique = np.vstack(
                    [self.item_dense_unique[:-1], new_items]
                )

    # sparse_indices and offset will increase if sparse feature encounter new categories
    def modify_sparse_indices(self):
        # old_offset = [i + 1 for i in self.old_sparse_oov[:-1]]
        # old_offset = np.insert(old_offset, 0, 0)
        old_offset = np.array(self.old_sparse_offset)
        if self.user_sparse_unique is not None:
            user_idx = self.user_sparse_col.index
            diff = self.sparse_offset[user_idx] - old_offset[user_idx]
            self.user_sparse_unique += diff
        if self.item_sparse_unique is not None:
            item_idx = self.item_sparse_col.index
            diff = self.sparse_offset[item_idx] - old_offset[item_idx]
            self.item_sparse_unique += diff

    # todo: ignore feature oov value
    def assign_sparse_features(self, data, mode):
        data = check_oov(self, data, mode)
        if mode == "user":
            row_idx = data["user"].to_numpy()
            col_info = self.user_sparse_col
            if self.user_sparse_unique is not None and col_info.name:
                for feat_idx, col in enumerate(col_info.name):
                    if col not in data.columns:
                        continue
                    self.user_sparse_unique[
                        row_idx, feat_idx
                    ] = compute_sparse_feat_indices(
                        self, data, col_info.index[feat_idx], col
                    )
        elif mode == "item":
            row_idx = data["item"].to_numpy()
            col_info = self.item_sparse_col
            if self.item_sparse_unique is not None and col_info.name:
                for feat_idx, col in enumerate(col_info.name):
                    if col not in data.columns:
                        continue
                    self.item_sparse_unique[
                        row_idx, feat_idx
                    ] = compute_sparse_feat_indices(
                        self, data, col_info.index[feat_idx], col
                    )
        else:
            raise ValueError("mode must be user or item.")

    def assign_dense_features(self, data, mode):
        data = check_oov(self, data, mode)
        if mode == "user":
            row_idx = data["user"].to_numpy()
            col_info = self.user_dense_col
            if self.user_dense_unique is not None and col_info.name:
                for feat_idx, col in enumerate(col_info.name):
                    if col not in data.columns:
                        continue
                    self.user_dense_unique[row_idx, feat_idx] = data[col].to_numpy()
        elif mode == "item":
            row_idx = data["item"].to_numpy()
            col_info = self.item_dense_col
            if self.item_dense_unique is not None and col_info.name:
                for feat_idx, col in enumerate(col_info.name):
                    if col not in data.columns:
                        continue
                    self.item_dense_unique[row_idx, feat_idx] = data[col].to_numpy()

    def assign_user_features(self, user_data):
        """Assign user features to this ``data_info`` object from ``user_data``.

        Parameters
        ----------
        user_data : pandas.DataFrame
            Data contains new user features.
        """
        self.assign_sparse_features(user_data, "user")
        self.assign_dense_features(user_data, "user")

    def assign_item_features(self, item_data):
        """Assign item features to this ``data_info`` object from ``item_data``.

        Parameters
        ----------
        item_data : pandas.DataFrame
            Data contains new item features.
        """
        self.assign_sparse_features(item_data, "item")
        self.assign_dense_features(item_data, "item")

    def add_oov(self):
        if (
            self.user_sparse_unique is not None
            and len(self.user_sparse_unique) == self.n_users
        ):
            user_sparse_oov = self.sparse_oov[self.user_sparse_col.index]
            self.user_sparse_unique = np.vstack(
                [self.user_sparse_unique, user_sparse_oov]
            )
        if (
            self.item_sparse_unique is not None
            and len(self.item_sparse_unique) == self.n_items
        ):
            item_sparse_oov = self.sparse_oov[self.item_sparse_col.index]
            self.item_sparse_unique = np.vstack(
                [self.item_sparse_unique, item_sparse_oov]
            )
        if (
            self.user_dense_unique is not None
            and len(self.user_dense_unique) == self.n_users
        ):
            user_dense_oov = np.mean(self.user_dense_unique, axis=0)
            self.user_dense_unique = np.vstack([self.user_dense_unique, user_dense_oov])
        if (
            self.item_dense_unique is not None
            and len(self.item_dense_unique) == self.n_items
        ):
            item_dense_oov = np.mean(self.item_dense_unique, axis=0)
            self.item_dense_unique = np.vstack([self.item_dense_unique, item_dense_oov])

    def set_popular_items(self, num):
        count_items = (
            self.interaction_data.drop_duplicates(subset=["user", "item"])
            .groupby("item")["user"]
            .count()
        )
        selected_items = count_items.sort_values(ascending=False).index.tolist()[:num]
        # if not enough items, add old populars
        if len(selected_items) < num and self.popular_items is not None:
            diff = num - len(selected_items)
            selected_items.extend(self.popular_items[:diff])
        self.popular_items = selected_items

    def store_args(self, user_indices, item_indices):
        self.all_args = dict()
        inside_args = [
            "col_name_mapping",
            "interaction_data",
            "user_sparse_unique",
            "user_dense_unique",
            "item_sparse_unique",
            "item_dense_unique",
            "user_unique_vals",
            "item_unique_vals",
            "sparse_unique_vals",
            "sparse_offset",
            "sparse_oov",
            "multi_sparse_unique_vals",
            "multi_sparse_combine_info",
        ]
        all_variables = vars(self)
        for arg in inside_args:
            if arg in all_variables and all_variables[arg] is not None:
                self.all_args[arg] = all_variables[arg]
        self.all_args["user_indices"] = user_indices
        self.all_args["item_indices"] = item_indices

    def save(self, path, model_name):
        """Save :class:`DataInfo` Object.

        Parameters
        ----------
        path : str
            File folder path to save :class:`DataInfo`.
        model_name : str
            Name of the saved file.
        """
        if not os.path.isdir(path):
            print(f"file folder {path} doesn't exists, creating a new one...")
            os.makedirs(path)
        if self.col_name_mapping is not None:
            name_mapping_path = os.path.join(
                path, f"{model_name}_data_info_name_mapping.json"
            )
            with open(name_mapping_path, "w") as f:
                json.dump(
                    self.all_args["col_name_mapping"],
                    f,
                    separators=(",", ":"),
                    indent=4,
                )

        other_path = os.path.join(path, f"{model_name}_data_info")
        hparams = dict()
        arg_names = inspect.signature(self.__init__).parameters.keys()
        for arg in arg_names:
            if (
                arg == "col_name_mapping"
                or arg not in self.all_args
                or self.all_args[arg] is None
            ):
                continue
            if arg == "interaction_data":
                hparams[arg] = self.all_args[arg].to_numpy()
            elif arg == "sparse_unique_vals":
                sparse_unique_vals = self.all_args[arg]
                for col, val in sparse_unique_vals.items():
                    hparams["unique_" + str(col)] = np.asarray(val)
            elif arg == "multi_sparse_unique_vals":
                multi_sparse_unique_vals = self.all_args[arg]
                for col, val in multi_sparse_unique_vals.items():
                    hparams["munique_" + str(col)] = np.asarray(val)
            else:
                hparams[arg] = self.all_args[arg]

        np.savez_compressed(other_path, **hparams)

    @classmethod
    def load(cls, path, model_name):
        """Load saved :class:`DataInfo`.

        Parameters
        ----------
        path : str
            File folder path to save :class:`DataInfo`.
        model_name : str
            Name of the saved file.
        """
        if not os.path.exists(path):
            raise OSError(f"file folder {path} doesn't exists...")

        hparams = dict()
        name_mapping_path = os.path.join(
            path, f"{model_name}_data_info_name_mapping.json"
        )
        if os.path.exists(name_mapping_path):
            with open(name_mapping_path, "r") as f:
                hparams["col_name_mapping"] = json.load(f)

        other_path = os.path.join(path, f"{model_name}_data_info.npz")
        info = np.load(other_path, allow_pickle=True)
        info = dict(info.items())
        for arg in info:
            if arg == "interaction_data":
                hparams[arg] = pd.DataFrame(
                    info[arg], columns=["user", "item", "label"]
                )
            elif arg == "multi_sparse_combine_info":
                # numpy can save MultiSparseInfo in 0-d array.
                hparams[arg] = info[arg].item()
            elif arg.startswith("unique_"):
                if "sparse_unique_vals" not in hparams:
                    hparams["sparse_unique_vals"] = dict()
                hparams["sparse_unique_vals"][arg[7:]] = info[arg]
            elif arg.startswith("munique_"):
                if "multi_sparse_unique_vals" not in hparams:
                    hparams["multi_sparse_unique_vals"] = dict()
                hparams["multi_sparse_unique_vals"][arg[8:]] = info[arg]
            else:
                hparams[arg] = info[arg]

        return cls(**hparams)
