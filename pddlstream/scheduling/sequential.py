from pddlstream.conversion import obj_from_pddl, obj_from_pddl_plan
from pddlstream.fast_downward import task_from_domain_problem, get_problem, solve_from_task, get_init, TOTAL_COST
from pddlstream.scheduling.simultaneous import get_stream_actions, evaluations_from_stream_plan, \
    extract_function_results, get_results_from_head
from pddlstream.utils import Verbose, find


# TODO: interpolate between all the scheduling options


def real_from_optimistic(evaluations, opt_task):
    import pddl
    import pddl_to_prolog
    import build_model
    import instantiate
    real_init = get_init(evaluations)
    opt_facts = set(opt_task.init) - set(real_init)
    with Verbose(False):
        model = build_model.compute_model(pddl_to_prolog.translate(opt_task))
        fluent_facts = instantiate.get_fluent_facts(opt_task, model) | opt_facts
    opt_task.init = real_init
    init_facts = set(opt_task.init)
    function_assignments = {fact.fluent: fact.expression for fact in init_facts
                            if isinstance(fact, pddl.f_expression.FunctionAssignment)}
    type_to_objects = instantiate.get_objects_by_type(opt_task.objects, opt_task.types)
    return fluent_facts, init_facts, function_assignments, type_to_objects


def sequential_stream_plan(evaluations, goal_expression, domain, stream_results, unit_costs=True, **kwargs):
    opt_evaluations = evaluations_from_stream_plan(evaluations, stream_results)
    problem = get_problem(opt_evaluations, goal_expression, domain, unit_costs)
    task = task_from_domain_problem(domain, problem)
    action_plan, action_cost = solve_from_task(task, **kwargs)
    if action_plan is None:
        return None, action_plan, action_cost

    fluent_facts, init_facts, function_assignments, type_to_objects = real_from_optimistic(evaluations, task)
    task.actions, stream_result_from_name = get_stream_actions(stream_results)
    results_from_head = get_results_from_head(opt_evaluations)

    # TODO: add ordering constraints to simplify the optimization
    import pddl
    action_from_name = {}
    function_plan = set()
    for i, (name, args) in enumerate(action_plan):
        action = find(lambda a: a.name == name, domain.actions)
        assert(len(action.parameters) == len(args))
        #parameters = action.parameters[:action.num_external_parameters]
        var_mapping = {p.name: a for p, a in zip(action.parameters, args)}
        new_name = '{}-{}'.format(name, i)
        new_parameters = action.parameters[len(args):]
        new_preconditions = []
        action.precondition.instantiate(var_mapping, init_facts, fluent_facts, new_preconditions)
        new_effects = []
        for eff in action.effects:
            eff.instantiate(var_mapping, init_facts, fluent_facts, type_to_objects, new_effects)
        new_effects = [pddl.Effect([], pddl.Conjunction(conditions), effect)
                      for conditions, effect in new_effects]
        cost = pddl.Increase(fluent=pddl.PrimitiveNumericExpression(symbol=TOTAL_COST, args=[]),
                             expression=pddl.NumericConstant(1))
        #cost = None
        task.actions.append(pddl.Action(new_name, new_parameters, 0,
                                   pddl.Conjunction(new_preconditions), new_effects, cost))
        action_from_name[new_name] = (name, map(obj_from_pddl, args))
        if not unit_costs:
            function_plan.update(extract_function_results(results_from_head, action, args))

    combined_plan, _ = solve_from_task(task, **kwargs)
    if combined_plan is None:
        return None, obj_from_pddl_plan(action_plan)
    stream_plan = []
    action_plan = []
    for name, args in combined_plan:
        if name in stream_result_from_name:
            stream_plan.append(stream_result_from_name[name])
        else:
            action_plan.append(action_from_name[name])
    return (stream_plan + list(function_plan)), action_plan, action_cost
