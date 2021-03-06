
"""

triangulation

This file contains functions that can be used to determine the position
of a sound in a mesh network given a set of nodeEvents with associated
information. The nodeEvent (at this point) is a simple struct containing
its x and y position, the confidence of the sound that was just detected,
and the sound pressure level of the sound when it was detected. Using this
information we can create a probability function that can be maximized to
determine the position of the sample sound. The sample sound (for localization
given that the sound has been accurately detected by a set of nodeEvents)
only needs to contain the reference sound pressure level and a reference
distance from which this measurement has been taken.

"""

# imported and not used so that the class would be in the same package
from detectionevent import DetectionEvent

from point import Point
from location import Location
from collections import namedtuple

import math
import scipy.optimize as opt
import sklearn.cluster as clustering # AffinityPropagation
import numpy as np


STD_SCALE =  1.4
MIN_DIST = 0.0001
EARTH_RADIUS = 1000 * 6371

# Special distance uncertainty threshold in meters
DISTANCE_THRESHOLD = 2


def distance_from_sound(r_ref, l_ref, l_current):
    """

    Determines the distance from a sound given the sound pressure level
    and a reference sound pressure level with an associated distance

    @param rRef The reference distance at which the reference sound
    pressure level was recorded

    @param lRef The reference sound pressure level used to determine the
    distance from the newly measured sound pressure level

    @param lCurrent Newly measured sound pressure level

    @return The predicted radius from a node event that the sound will be
    located at given the current sound pressure level.

    """

    return r_ref * math.pow(10, (l_ref - l_current) / float(20))


def distance_from_detection_event(x, y, node_event):
    """

    Given x and y coordinates, this returns the distance to a nodeEvent
    where the nodeEvent has attributes, x and y, on the same plane

    @param x the horizontal location of the node event when the node event
    was captured

    @param y the vertical location of the node event when the node event
    was captured

    @param nodeEvent The associated data when a node detects with some
    confidence that the sound has been identified

    @return The distance from a node event given x and y coordinates

    """

    lat1 = math.radians(x)
    lon1 = math.radians(y)
    lat2 = math.radians(node_event.x)
    lon2 = math.radians(node_event.y)

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = (
        (math.sin(dlat / 2)) ** 2 +
        math.cos(lat1) * math.cos(lat2) * (math.sin(dlon / 2)) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = EARTH_RADIUS * c

    return distance


def normal_distribution(x):
    """

    This is the normal distribution function

    @param x Input for the normal distribution function

    @return The resulting value for the probability desnsity function

    """

    return (1 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * math.pow(x, 2))


def set_node_events_std(node_events):
    """

    Uses the relative time differences between the node events mixed with
    the confidence of sound recognition to determine the standard deviation
    of the node event. Node events that are closest to the node event that has
    the largest time stamps will have a lower standard deviation. Also, node
    events that have a larger sound recognition confidence will be given lower
    standard deviations.

    @param nodeEvents The list of associated data when a node detects with some
    confidence that the sound has been identified

    """

    if len(node_events) == 0:
        raise ValueError("Node event list is of length 0")

    max_time = 0
    min_time = node_events[0].get_timestamp()
    for node_event in node_events:
        if node_event.get_timestamp() > max_time:
            max_time = node_event.get_timestamp()
        elif node_event.get_timestamp() < min_time:
            min_time = node_event.get_timestamp()

    for node_event in node_events:
        time_error = 1.0 - (
            (max_time - node_event.get_timestamp()) /
            (max_time - min_time + 1)
        )
        node_event.set_std(STD_SCALE / (node_event.confidence + time_error))


def position_evaluation(x, y, r_ref, l_ref, node_events):
    """

    Evaluation function to deterimine with some weight, where a sound is
    located in the mesh network of nodes. Given an x and y, this returns
    a weight. The higher the weight, the higher the likelihood that the
    sound originated from x and y.

    @param x the horizontal location of the node event when the node event
    was captured

    @param y the vertical location of the node event when the node event
    was captured

    @param rRef The reference distance at which the reference sound
    pressure level was recorded

    @param lRef The reference sound pressure level used to determine the
    distance from the newly measured sound pressure level

    @param nodeEvents The list of associated data when a node detects with some
    confidence that the sound has been identified

    @return The a result, given independent variables, x and y, and a
    configuration of node events with per sample sound constants, rRef and
    lRef, will be a value representing the likelihood of the sample sound
    being located at position (x, y).

    """

    set_node_events_std(node_events)

    return sum(
        [
            normal_distribution(
                (
                    distance_from_detection_event(x, y, n) -
                    distance_from_sound(r_ref, l_ref, n.spl)
                ) / n.get_std()
            ) / n.get_std() for n in node_events
        ]
    )


def position_probability(x, y, r_ref, l_ref, node_events):
    """

    Scales the evaluation function so it returns a probability (i.e. a float
    between 0 and 1 inclusive) that a given x and y is where a sample sound
    originated from

    @param x the horizontal location of the node event when the node event
    was captured

    @param y the vertical location of the node event when the node event
    was captured

    @param rRef The reference distance at which the reference sound
    pressure level was recorded

    @param lRef The reference sound pressure level used to determine the
    distance from the newly measured sound pressure level

    @param nodeEvents The list ofassociated data when a node detects with some
    confidence that the sound has been identified

    @return The a result, given independent variables, x and y, and a
    configuration of node events with per sample sound constants, rRef and
    lRef, will be a value representing the probability of the sample
    sound being located at position (x, y).

    """

    return position_evaluation(
        x, y,
        r_ref, l_ref,
        node_events
    ) / float(len(node_events))


def determine_sound_position_list(r_ref, l_ref, node_events, **kwargs):
    """

    Determines a list of possible positions of where the sound will be
    located. These positions are determined by changing iterating through
    the list of node events and optimizing the probability density function
    with the initial guess being the position of the node event. *Hopefully*
    the optimization will find the local minima.

    @param rRef The reference distance at which the reference sound
    pressure level was recorded

    @param lRef The reference sound pressure level used to determine the
    distance from the newly measured sound pressure level

    @param nodeEvents The list ofassociated data when a node detects with some
    confidence that the sound has been identified

    @return A list of the possible x and y positions of the sound.

    """

    p_func = lambda v: -1 * position_probability(
        v[0], v[-1],
        r_ref, l_ref,
        node_events
    )

    max_list = [
        opt.fmin(p_func, ne.get_pos(), full_output=1, **kwargs)
        for ne in node_events
    ]

    max_vals = [
        (Point(x, y), -z) for (x, y), z, _, _, _ in max_list
    ]

    return max_vals


def determine_peaks(opt_vals, label_list):
    """

    Given a list of "optimized" points and their corresponding probabilities
    and a list of labels returned from the clustering algorithm, this
    function goes through all of the optimized points and returns the ones with
    the highest probabilities and issues them as cluster centers. This function
    is used to ensure that the center for each cluster also has the highest
    probability in the cluster of being the sound position.

    @param opt_vals A list of tuples where each element is a key-value pair
    where the key is the Point object of the optimization x and y position
    and the value is the associated probability

    @param label_list A list of integers where the index of the list
    corresponds to a certain key-value pair in the first parameter
    list and the integer value represents which cluster it belongs to.

    """

    max_prob_list = list()
    max_point_list = list()
    for i, (point, prob) in zip(label_list, opt_vals):
        try:
            if max_prob_list[i] < prob:
                max_point_list[i] = point
                max_prob_list[i] = prob
        except IndexError:
            max_point_list.append(point)
            max_prob_list.append(prob)

    ret_list = list()
    for max_point in max_point_list:
        too_close = False
        for ret_point in ret_list:
            if ret_point.dist_to_lat_long(max_point) < MIN_DIST:
                too_close = True
                break
        if not too_close:
            ret_list.append(max_point)

    return ret_list


def determine_sound_locations_instance(r_ref, l_ref, node_events, **kwargs):
    """

    Determines the position in the probability grid that has the highest
    probability of being the position of the sound.

    @param rRef The reference distance at which the reference sound
    pressure level was recorded

    @param lRef The reference sound pressure level used to determine the
    distance from the newly measured sound pressure level

    @param nodeEvents The list ofassociated data when a node detects with some
    confidence that the sound has been identified

    @return A list of the x and y positions of the sound.

    """

    max_vals = determine_sound_position_list(
        r_ref, l_ref,
        node_events,
        **kwargs
    )

    positions = np.array([p.to_list() for p, _ in max_vals])

    af = clustering.AffinityPropagation().fit(positions)

    max_prob_centers = determine_peaks(max_vals, af.labels_)

    prob_list = [
        position_probability(
            p.x, p.y, r_ref, l_ref,
            node_events
        ) for p in max_prob_centers
    ]

    ret_list = [
        Location(p, conf)
        for p, conf in zip(max_prob_centers, prob_list)
    ]

    return ret_list


def evaluate_location_list(location_list):

    if location_list == None:
        return 0

    locations_conf = 0
    for location in location_list:
        locations_conf += location.get_confidence()

    return locations_conf


def determine_reference_data(r_ref, l_ref, node_events, **kwargs):

    pos_func = lambda ref: -1 * evaluate_location_list(
        determine_sound_locations_instance(
            ref[0], ref[1],
            node_events,
            **kwargs
        )
    )

    opt_output = opt.fmin(pos_func, [r_ref, l_ref], full_output=1, **kwargs)

    r_opt, l_opt = opt_output[0]

    return r_opt, l_opt


def get_node_distance_lists(r_ref, l_ref, node_events, locations):

    distance_lists = list()

    for location in locations:

        distance_list = list()

        for node_event in node_events:
            actual_distance= distance_from_detection_event(
                location.x,
                location.y,
                node_event
            )

            predicted_distance = distance_from_sound(
                r_ref, l_ref,
                node_event.get_spl()
            )

            distance_list.append(abs(predicted_distance - actual_distance))

        distance_lists.append(distance_list)

    return distance_lists


def associate_node_events(r_ref, l_ref, node_events, locations):
    """

    Checks with node events correspond to which peaks so we can optimize
    the reference distance and the reference sound pressure level. If we
    know the node event association, we can partition the problem into
    multiple sets of node events for multiple peaks. Then using this
    partitioning, we can optimize different values or r_ref and l_ref for
    different sound occurences

    """

    distance_lists = get_node_distance_lists(
        r_ref, l_ref,
        node_events,
        locations
    )

    association_dict = dict()

    for location_index, distance_list in enumerate(distance_lists):
        for node_index, distance in enumerate(distance_list):

            if distance < DISTANCE_THRESHOLD:
                if not location_index in association_dict.keys():
                    association_dict[locations[location_index]] = list()
                association_dict[locations[location_index]].append(
                    node_events[node_index]
                )

    return association_dict


def determine_sound_locations(r_ref, l_ref, node_events, **kwargs):

    initial_sound_locations = determine_sound_locations_instance(
        r_ref, l_ref,
        node_events,
        **kwargs
    )

    node_event_associations = associate_node_events(
        r_ref, l_ref,
        node_events,
        initial_sound_locations
    )

    location_list = list()

    for event_list in node_event_associations.values():
        r_opt, l_opt = determine_reference_data(
            r_ref, l_ref,
            event_list,
            **kwargs
        )

        location_list += determine_sound_locations_instance(
            r_opt, l_opt,
            event_list,
            **kwargs
        )

    return location_list


