import sys

import pytest
import tensorflow as tf

from libreco.algorithms import FM
from tests.utils_data import SAVE_PATH, remove_path, set_ranking_labels
from tests.utils_metrics import get_metrics
from tests.utils_multi_sparse_models import fit_multi_sparse
from tests.utils_pred import ptest_preds
from tests.utils_reco import ptest_recommends
from tests.utils_save_load import save_load_model


@pytest.mark.parametrize(
    "task, loss_type, sampler",
    [
        ("rating", "focal", "random"),
        ("ranking", "cross_entropy", None),
        ("ranking", "focal", None),
        ("ranking", "cross_entropy", "random"),
        ("ranking", "cross_entropy", "unconsumed"),
        ("ranking", "focal", "popular"),
        ("ranking", "unknown", "popular"),
    ],
)
@pytest.mark.parametrize(
    "lr_decay, reg, num_neg, use_bn, dropout_rate, num_workers",
    [
        (False, None, 1, False, None, 0),
        (True, 0.001, 3, True, 0.5, 2),
        (True, 0.001, 3, True, 0.5, -1),
    ],
)
def test_fm(
    prepare_feat_data,
    task,
    loss_type,
    sampler,
    lr_decay,
    reg,
    num_neg,
    use_bn,
    dropout_rate,
    num_workers,
):
    if not sys.platform.startswith("linux") and num_workers > 0:
        pytest.skip(
            "Windows and macOS use `spawn` in multiprocessing, which does not work well in pytest"
        )
    tf.compat.v1.reset_default_graph()
    pd_data, train_data, eval_data, data_info = prepare_feat_data
    if task == "ranking":
        # train_data.build_negative_samples(data_info, seed=2022)
        eval_data.build_negative_samples(data_info, seed=2222)
        if sampler is None and loss_type == "cross_entropy":
            set_ranking_labels(train_data)

    if task == "ranking" and loss_type not in ("cross_entropy", "focal"):
        with pytest.raises(ValueError):
            FM(task, data_info, loss_type).fit(train_data)
    elif task == "ranking" and sampler is None and loss_type == "focal":
        with pytest.raises(ValueError):
            FM(task, data_info, loss_type, sampler=sampler).fit(train_data)
    elif num_workers < 0:
        with pytest.raises(ValueError):
            FM(task, data_info, loss_type).fit(train_data, num_workers=num_workers)
    else:
        model = FM(
            task=task,
            data_info=data_info,
            loss_type=loss_type,
            embed_size=16,
            n_epochs=1,
            lr=1e-4,
            lr_decay=lr_decay,
            reg=reg,
            batch_size=1024,
            sampler=sampler,
            num_neg=num_neg,
            use_bn=use_bn,
            dropout_rate=dropout_rate,
            tf_sess_config=None,
        )
        model.fit(
            train_data,
            verbose=2,
            shuffle=True,
            eval_data=eval_data,
            metrics=get_metrics(task),
            eval_user_num=200,
            num_workers=num_workers,
        )
        ptest_preds(model, task, pd_data, with_feats=True)
        ptest_recommends(model, data_info, pd_data, with_feats=True)


def test_fm_multi_sparse(prepare_multi_sparse_data):
    task = "ranking"
    pd_data, train_data, eval_data, data_info = prepare_multi_sparse_data
    model = fit_multi_sparse(FM, train_data, eval_data, data_info)
    ptest_preds(model, task, pd_data, with_feats=True)
    ptest_recommends(model, data_info, pd_data, with_feats=True)
    model.save("not_existed_path", "fm2", manual=True, inference_only=True)
    remove_path("not_existed_path")

    # test save and load model
    loaded_model, loaded_data_info = save_load_model(FM, model, data_info)
    ptest_preds(loaded_model, task, pd_data, with_feats=True)
    ptest_recommends(loaded_model, loaded_data_info, pd_data, with_feats=True)

    # test save and load model with `manual=False`
    loaded_model.save(SAVE_PATH, "fm_model", manual=False, inference_only=False)
    tf.compat.v1.reset_default_graph()
    loaded_model = FM.load(SAVE_PATH, "fm_model", loaded_data_info, manual=False)
    ptest_preds(loaded_model, task, pd_data, with_feats=True)
    ptest_recommends(loaded_model, loaded_data_info, pd_data, with_feats=True)
